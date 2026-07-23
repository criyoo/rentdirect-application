#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

WORKSPACE="${1:-${WORKSPACE:-dev}}"
PROJECT_NAME="${PROJECT_NAME:-rentdirect}"
ENVIRONMENT="${ENVIRONMENT:-${WORKSPACE}}"
AWS_WORKLOAD_PROFILE="${AWS_WORKLOAD_PROFILE:-${WORKSPACE}-rentdirect}"
AWS_REGION="${AWS_REGION:-eu-west-1}"
REGION="${AWS_REGION}"
NAME_PREFIX="${PROJECT_NAME}-${ENVIRONMENT}"
ECS_CLUSTER_NAME="${ECS_CLUSTER_NAME:-}"
ADMIN_TASK_DEFINITION="${ADMIN_TASK_DEFINITION:-}"
ADMIN_TASK_CONTAINER_NAME="${ADMIN_TASK_CONTAINER_NAME:-migration}"
ADMIN_START_DB_INSTANCE="${ADMIN_START_DB_INSTANCE:-1}"
ADMIN_LOG_GROUP="${ADMIN_LOG_GROUP:-/ecs/${NAME_PREFIX}/migration}"
PUBLIC_SUBNET_IDS="${PUBLIC_SUBNET_IDS:-}"
APP_SECURITY_GROUP_ID="${APP_SECURITY_GROUP_ID:-}"
DJANGO_SUPERUSER_PASSWORD="${DJANGO_SUPERUSER_PASSWORD:-${ADMIN_PASSWORD:-}}"

if [ -z "${ADMIN_EMAIL:-}" ]; then
  if [ "${ENVIRONMENT}" = "dev" ]; then
    ADMIN_EMAIL="admin@dev.rentdirect.homes"
  else
    ADMIN_EMAIL="admin@rentdirect.homes"
  fi
fi

export AWS_PAGER=""

fail() {
  echo "Error: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

set_aws_auth_mode() {
  if [ "${AWS_USE_PROFILE:-1}" = "0" ]; then
    AWS_PROFILE_ARGS=()
    return
  fi

  if [ -n "${AWS_ACCESS_KEY_ID:-}" ] ||
    [ -n "${AWS_WEB_IDENTITY_TOKEN_FILE:-}" ] ||
    [ -n "${AWS_CONTAINER_CREDENTIALS_RELATIVE_URI:-}" ] ||
    [ -n "${AWS_CONTAINER_CREDENTIALS_FULL_URI:-}" ]; then
    AWS_PROFILE_ARGS=()
    return
  fi

  unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
  unset AWS_SECURITY_TOKEN AWS_SESSION_EXPIRATION AWS_ACCESS_KEY AWS_SECRET_KEY

  AWS_PROFILE_ARGS=(--profile "${AWS_WORKLOAD_PROFILE}")
}

aws_with_auth() {
  aws "${AWS_PROFILE_ARGS[@]}" "$@"
}

read_superuser_password() {
  local parameter_name
  local parameter_value
  local parameter_names

  if [ -n "${DJANGO_SUPERUSER_PASSWORD}" ]; then
    return
  fi

  parameter_names=(
    "/${PROJECT_NAME}/${ENVIRONMENT}/DJANGO_SUPERUSER_PASSWORD"
    "/${PROJECT_NAME}/${ENVIRONMENT}/ADMIN_PASSWORD"
    "/${PROJECT_NAME}/secret/${ENVIRONMENT}/DJANGO_SUPERUSER_PASSWORD"
  )

  for parameter_name in "${parameter_names[@]}"; do
    if parameter_value="$(aws_with_auth ssm get-parameter \
      --region "${REGION}" \
      --name "${parameter_name}" \
      --with-decryption \
      --query "Parameter.Value" \
      --output text 2>/dev/null)"; then
      if [ -n "${parameter_value}" ] && [ "${parameter_value}" != "None" ]; then
        DJANGO_SUPERUSER_PASSWORD="${parameter_value}"
        return
      fi
    fi
  done
}

build_overrides_json() {
  ADMIN_EMAIL="${ADMIN_EMAIL}" \
  DJANGO_SUPERUSER_PASSWORD="${DJANGO_SUPERUSER_PASSWORD}" \
  ADMIN_TASK_CONTAINER_NAME="${ADMIN_TASK_CONTAINER_NAME}" \
  python3 - <<'PY'
import json
import os

command = (
    'cd /app && python manage.py shell -c "'
    "from django.contrib.auth import get_user_model; import os; "
    "User = get_user_model(); "
    "email = os.environ['DJANGO_SUPERUSER_EMAIL']; "
    "password = os.environ['DJANGO_SUPERUSER_PASSWORD']; "
    "user, created = User.objects.get_or_create(email=email, defaults={'role': 'admin'}); "
    "user.role = 'admin'; "
    "user.email_verified = True; "
    "user.is_staff = True; "
    "user.is_superuser = True; "
    "user.is_active = True; "
    "user.set_password(password); "
    "user.save(); "
    "print('Superuser ready: ' + email + (' (created)' if created else ' (updated)'))"
    '"'
)

payload = {
    "containerOverrides": [
        {
            "name": os.environ["ADMIN_TASK_CONTAINER_NAME"],
            "command": ["sh", "-lc", command],
            "environment": [
                {"name": "MIGRATE_ON_STARTUP", "value": os.environ.get("MIGRATE_ON_STARTUP", "1")},
                {"name": "SEED_DEMO_ACCOUNTS", "value": os.environ.get("SEED_DEMO_ACCOUNTS", "1")},
                {"name": "DJANGO_SUPERUSER_EMAIL", "value": os.environ["ADMIN_EMAIL"]},
                {"name": "DJANGO_SUPERUSER_PASSWORD", "value": os.environ["DJANGO_SUPERUSER_PASSWORD"]},
                {"name": "DJANGO_SUPERUSER_NAME", "value": "Admin"},
            ],
        }
    ]
}

print(json.dumps(payload))
PY
}

resolve_service_network_value() {
  local query="$1"

  aws_with_auth ecs describe-services \
    --region "${REGION}" \
    --cluster "${CLUSTER_NAME}" \
    --services "${API_SERVICE_NAME}" \
    --query "${query}" \
    --output text 2>/dev/null || true
}

ensure_db_available() {
  local db_instance_identifier="${DB_INSTANCE_IDENTIFIER:-${NAME_PREFIX}-postgres}"
  local db_status

  db_status="$(aws_with_auth rds describe-db-instances \
    --region "${REGION}" \
    --db-instance-identifier "${db_instance_identifier}" \
    --query 'DBInstances[0].DBInstanceStatus' \
    --output text)"

  [ -n "${db_status}" ] && [ "${db_status}" != "None" ] || fail "Could not resolve RDS instance ${db_instance_identifier}."

  case "${db_status}" in
    available)
      ;;
    starting|backing-up|configuring-enhanced-monitoring|configuring-iam-database-auth|maintenance|modifying|rebooting|renaming|resetting-master-credentials|storage-optimization|upgrading)
      aws_with_auth rds wait db-instance-available \
        --region "${REGION}" \
        --db-instance-identifier "${db_instance_identifier}"
      ;;
    stopped)
      [ "${ADMIN_START_DB_INSTANCE}" = "1" ] || fail "RDS instance ${db_instance_identifier} is stopped."
      aws_with_auth rds start-db-instance \
        --region "${REGION}" \
        --db-instance-identifier "${db_instance_identifier}" >/dev/null
      aws_with_auth rds wait db-instance-available \
        --region "${REGION}" \
        --db-instance-identifier "${db_instance_identifier}"
      ;;
    stopping)
      fail "RDS instance ${db_instance_identifier} is stopping. Retry after it has stopped or become available."
      ;;
    *)
      fail "RDS instance ${db_instance_identifier} is not ready for admin provisioning: ${db_status}"
      ;;
  esac
}

print_task_failure_summary() {
  local task_arn="$1"

  aws_with_auth ecs describe-tasks \
    --region "${REGION}" \
    --cluster "${CLUSTER_NAME}" \
    --tasks "${task_arn}" \
    --query 'tasks[0].{stopCode:stopCode,stoppedReason:stoppedReason,containerName:containers[0].name,containerReason:containers[0].reason,exitCode:containers[0].exitCode}' \
    --output json >&2 || true
}

print_task_logs() {
  local task_arn="$1"
  local task_id="${task_arn##*/}"
  local log_stream_name

  log_stream_name="$(aws_with_auth logs describe-log-streams \
    --region "${REGION}" \
    --log-group-name "${ADMIN_LOG_GROUP}" \
    --log-stream-name-prefix "migration/${ADMIN_TASK_CONTAINER_NAME}/${task_id}" \
    --query 'logStreams[0].logStreamName' \
    --output text 2>/dev/null || true)"

  if [ -z "${log_stream_name}" ] || [ "${log_stream_name}" = "None" ]; then
    return
  fi

  aws_with_auth logs get-log-events \
    --region "${REGION}" \
    --log-group-name "${ADMIN_LOG_GROUP}" \
    --log-stream-name "${log_stream_name}" \
    --limit 200 \
    --query 'events[*].message' \
    --output text 2>/dev/null | tr '\t' '\n' >&2 || true
}

require_cmd aws
require_cmd python3
require_cmd tr

set_aws_auth_mode
read_superuser_password

[ -n "${DJANGO_SUPERUSER_PASSWORD}" ] || fail "DJANGO_SUPERUSER_PASSWORD is required"

CLUSTER_NAME="${ECS_CLUSTER_NAME:-${NAME_PREFIX}-cluster}"
TASK_DEFINITION="${ADMIN_TASK_DEFINITION:-${NAME_PREFIX}-migration}"
API_SERVICE_NAME="${NAME_PREFIX}-api"

ensure_db_available

if [ -z "${PUBLIC_SUBNET_IDS}" ]; then
  PUBLIC_SUBNET_IDS="$(aws_with_auth ec2 describe-subnets \
    --region "${REGION}" \
    --filters \
      "Name=tag:Project,Values=${PROJECT_NAME}" \
      "Name=tag:Environment,Values=${ENVIRONMENT}" \
      "Name=tag:Tier,Values=public" \
    --query 'Subnets[].SubnetId' \
    --output text)"

  if [ -z "${PUBLIC_SUBNET_IDS}" ] || [ "${PUBLIC_SUBNET_IDS}" = "None" ]; then
    PUBLIC_SUBNET_IDS="$(resolve_service_network_value 'services[0].networkConfiguration.awsvpcConfiguration.subnets')"
  fi
fi

[ -n "${PUBLIC_SUBNET_IDS}" ] && [ "${PUBLIC_SUBNET_IDS}" != "None" ] || fail "Could not resolve public subnets for ${NAME_PREFIX}"

if [ -z "${APP_SECURITY_GROUP_ID}" ]; then
  APP_SECURITY_GROUP_ID="$(aws_with_auth ec2 describe-security-groups \
    --region "${REGION}" \
    --filters "Name=group-name,Values=${NAME_PREFIX}-app" \
    --query 'SecurityGroups[0].GroupId' \
    --output text)"

  if [ -z "${APP_SECURITY_GROUP_ID}" ] || [ "${APP_SECURITY_GROUP_ID}" = "None" ]; then
    APP_SECURITY_GROUP_ID="$(resolve_service_network_value 'services[0].networkConfiguration.awsvpcConfiguration.securityGroups[0]')"
  fi
fi

[ -n "${APP_SECURITY_GROUP_ID}" ] && [ "${APP_SECURITY_GROUP_ID}" != "None" ] || fail "Could not resolve app security group for ${NAME_PREFIX}"

TASK_DEFINITION_ARN="$(aws_with_auth ecs describe-task-definition \
  --region "${REGION}" \
  --task-definition "${TASK_DEFINITION}" \
  --query 'taskDefinition.taskDefinitionArn' \
  --output text)"

[ -n "${TASK_DEFINITION_ARN}" ] && [ "${TASK_DEFINITION_ARN}" != "None" ] || fail "Could not resolve ECS task definition ${TASK_DEFINITION}"

IFS=$'\t \n,' read -r -a SUBNET_IDS <<< "${PUBLIC_SUBNET_IDS}"
[ "${#SUBNET_IDS[@]}" -gt 0 ] || fail "No public subnet IDs available for the admin task"

subnet_csv="$(IFS=,; echo "${SUBNET_IDS[*]}")"
network_configuration="awsvpcConfiguration={subnets=[${subnet_csv}],securityGroups=[${APP_SECURITY_GROUP_ID}],assignPublicIp=ENABLED}"
overrides_json="$(build_overrides_json)"

echo "Creating or updating ${ADMIN_EMAIL} with task definition ${TASK_DEFINITION_ARN}..."
TASK_ARN="$(aws_with_auth ecs run-task \
  --region "${REGION}" \
  --cluster "${CLUSTER_NAME}" \
  --launch-type FARGATE \
  --task-definition "${TASK_DEFINITION_ARN}" \
  --network-configuration "${network_configuration}" \
  --overrides "${overrides_json}" \
  --started-by "admin-user-noninteractive" \
  --query 'tasks[0].taskArn' \
  --output text)"

[ -n "${TASK_ARN}" ] && [ "${TASK_ARN}" != "None" ] || fail "Failed to start the admin creation task in cluster ${CLUSTER_NAME}"

echo "Task ARN: ${TASK_ARN}"

aws_with_auth ecs wait tasks-stopped \
  --region "${REGION}" \
  --cluster "${CLUSTER_NAME}" \
  --tasks "${TASK_ARN}"

TASK_EXIT_CODE="$(aws_with_auth ecs describe-tasks \
  --region "${REGION}" \
  --cluster "${CLUSTER_NAME}" \
  --tasks "${TASK_ARN}" \
  --query 'tasks[0].containers[0].exitCode' \
  --output text)"

if [ "${TASK_EXIT_CODE}" != "0" ]; then
  print_task_failure_summary "${TASK_ARN}"
  print_task_logs "${TASK_ARN}"
  fail "Admin user task failed."
fi

print_task_logs "${TASK_ARN}"
echo "Admin user ready: ${ADMIN_EMAIL}"
