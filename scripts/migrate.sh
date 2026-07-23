#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

WORKSPACE="${1:-${WORKSPACE:-dev}}"
PROJECT_NAME="${PROJECT_NAME:-rentdirect}"
ENVIRONMENT="${ENVIRONMENT:-${WORKSPACE}}"
AWS_REGION="${AWS_REGION:-eu-west-1}"
REGION="${AWS_REGION}"
AWS_WORKLOAD_PROFILE="${AWS_WORKLOAD_PROFILE:-${ENVIRONMENT}-${PROJECT_NAME}}"
PUBLIC_SUBNET_IDS="${PUBLIC_SUBNET_IDS:-}"
APP_SECURITY_GROUP_ID="${APP_SECURITY_GROUP_ID:-}"
ECS_CLUSTER_NAME="${ECS_CLUSTER_NAME:-}"
MIGRATION_TASK_DEFINITION="${MIGRATION_TASK_DEFINITION:-}"
MIGRATION_LOG_GROUP="${MIGRATION_LOG_GROUP:-}"
MIGRATE_ON_STARTUP="${MIGRATE_ON_STARTUP:-0}"
SEED_DEMO_ACCOUNTS="${SEED_DEMO_ACCOUNTS:-0}"
ENSURE_SUPERUSER_AFTER_MIGRATION="${ENSURE_SUPERUSER_AFTER_MIGRATION:-0}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@rentdirect.homes}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"
ADMIN_NAME="${ADMIN_NAME:-Admin}"
MIGRATION_START_DB_INSTANCE="${MIGRATION_START_DB_INSTANCE:-0}"
DEPLOY_IMAGE_URI="${DEPLOY_IMAGE_URI:-}"
RUN_TASK_DEFINITION_ARN="${RUN_TASK_DEFINITION_ARN:-}"

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

json_escape() {
  local value="$1"

  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"

  printf '%s' "${value}"
}

build_task_overrides() {
  local command="$1"
  local environment_json

  environment_json='[{"name":"MIGRATE_ON_STARTUP","value":"'"${MIGRATE_ON_STARTUP}"'"},{"name":"SEED_DEMO_ACCOUNTS","value":"'"${SEED_DEMO_ACCOUNTS}"'"}]'

  if [ "${ENSURE_SUPERUSER_AFTER_MIGRATION}" = "1" ]; then
    [ -n "${ADMIN_PASSWORD}" ] || fail "ADMIN_PASSWORD is required when ENSURE_SUPERUSER_AFTER_MIGRATION=1"
    environment_json="$(printf '[{"name":"MIGRATE_ON_STARTUP","value":"'"${MIGRATE_ON_STARTUP}"'"},{"name":"SEED_DEMO_ACCOUNTS","value":"'"${SEED_DEMO_ACCOUNTS}"'"},{"name":"DJANGO_SUPERUSER_EMAIL","value":"%s"},{"name":"DJANGO_SUPERUSER_PASSWORD","value":"%s"},{"name":"DJANGO_SUPERUSER_NAME","value":"%s"}]' "$(json_escape "${ADMIN_EMAIL}")" "$(json_escape "${ADMIN_PASSWORD}")" "$(json_escape "${ADMIN_NAME}")")"
  fi

  printf '{"containerOverrides":[{"name":"migration","command":["sh","-lc","%s"],"environment":%s}]}' "$(json_escape "${command}")" "${environment_json}"
}

build_post_migration_command() {
  local command

  command="set -eu; python manage.py migrate --noinput"

  if [ "${SEED_DEMO_ACCOUNTS}" = "1" ]; then
    command="${command}; python manage.py seed_demo_data"
  fi

  if [ "${ENSURE_SUPERUSER_AFTER_MIGRATION}" = "1" ]; then
    command="${command}; if python manage.py shell -c \"from django.contrib.auth import get_user_model; import sys; sys.exit(0 if get_user_model().objects.filter(is_superuser=True).exists() else 1)\"; then echo 'Django superuser already exists; skipping admin bootstrap.'; else python manage.py ensure_superuser; fi"
  fi

  printf '%s' "${command}"
}

build_task_definition_payload() {
  local image_uri="$1"
  local source_file="$2"

  python3 - "$image_uri" "$source_file" <<'PY'
import json
import sys

image_uri = sys.argv[1]
source_file = sys.argv[2]

with open(source_file, "r", encoding="utf-8") as handle:
    task_definition = json.load(handle)

allowed_keys = [
    "family",
    "taskRoleArn",
    "executionRoleArn",
    "networkMode",
    "containerDefinitions",
    "volumes",
    "placementConstraints",
    "requiresCompatibilities",
    "cpu",
    "memory",
    "runtimePlatform",
    "pidMode",
    "ipcMode",
    "proxyConfiguration",
    "inferenceAccelerators",
    "ephemeralStorage",
]

payload = {
    key: task_definition[key]
    for key in allowed_keys
    if key in task_definition and task_definition[key] not in (None, [], {})
}

for container in payload.get("containerDefinitions", []):
    if container.get("name") == "migration":
        container["image"] = image_uri

print(json.dumps(payload))
PY
}

resolve_task_definition_arn() {
  if [ -n "${RUN_TASK_DEFINITION_ARN}" ]; then
    printf '%s\n' "${RUN_TASK_DEFINITION_ARN}"
    return
  fi

  local base_task_definition_arn
  base_task_definition_arn="$(aws_with_auth ecs describe-task-definition \
    --region "${REGION}" \
    --task-definition "${TASK_DEFINITION}" \
    --query 'taskDefinition.taskDefinitionArn' \
    --output text)"

  [ -n "${base_task_definition_arn}" ] && [ "${base_task_definition_arn}" != "None" ] ||
    fail "Could not resolve ECS migration task definition ${TASK_DEFINITION}"

  if [ -n "${DEPLOY_IMAGE_URI}" ]; then
    local source_file
    local payload_file

    source_file="$(mktemp)"
    payload_file="$(mktemp)"

    aws_with_auth ecs describe-task-definition \
      --region "${REGION}" \
      --task-definition "${base_task_definition_arn}" \
      --query 'taskDefinition' \
      --output json >"${source_file}"

    build_task_definition_payload "${DEPLOY_IMAGE_URI}" "${source_file}" >"${payload_file}"

    RUN_TASK_DEFINITION_ARN="$(aws_with_auth ecs register-task-definition \
      --region "${REGION}" \
      --cli-input-json "file://${payload_file}" \
      --query 'taskDefinition.taskDefinitionArn' \
      --output text)"

    rm -f "${source_file}" "${payload_file}"
  else
    RUN_TASK_DEFINITION_ARN="${base_task_definition_arn}"
  fi

  [ -n "${RUN_TASK_DEFINITION_ARN}" ] && [ "${RUN_TASK_DEFINITION_ARN}" != "None" ] ||
    fail "Could not prepare ECS migration task definition ${TASK_DEFINITION}"

  printf '%s\n' "${RUN_TASK_DEFINITION_ARN}"
}

print_task_logs() {
  local task_id="$1"
  local log_stream_name
  local task_logs

  log_stream_name="$(aws_with_auth logs describe-log-streams \
    --region "${REGION}" \
    --log-group-name "${MIGRATION_LOG_GROUP}" \
    --log-stream-name-prefix "ecs/migration/${task_id}" \
    --query 'logStreams[0].logStreamName' \
    --output text 2>/dev/null || true)"

  if [ -z "${log_stream_name}" ] || [ "${log_stream_name}" = "None" ]; then
    echo "Migration task CloudWatch log stream was not found in ${MIGRATION_LOG_GROUP} for task ${task_id}." >&2
    return
  fi

  echo "Migration task CloudWatch logs from ${MIGRATION_LOG_GROUP}:${log_stream_name}:" >&2
  task_logs="$(aws_with_auth logs get-log-events \
    --region "${REGION}" \
    --log-group-name "${MIGRATION_LOG_GROUP}" \
    --log-stream-name "${log_stream_name}" \
    --limit 200 \
    --query 'events[*].message' \
    --output text 2>/dev/null || true)"

  if [ -z "${task_logs}" ] || [ "${task_logs}" = "None" ]; then
    echo "(no log events found)" >&2
    return
  fi

  printf '%s\n' "${task_logs}" | tr '\t' '\n' >&2
}

run_ecs_task() {
  local description="$1"
  local overrides="${2:-}"
  local -a run_task_args

  run_task_args=(
    aws_with_auth ecs run-task
    --region "${REGION}"
    --cluster "${CLUSTER_NAME}"
    --launch-type FARGATE
    --task-definition "${TASK_DEFINITION_ARN}"
    --network-configuration "${network_configuration}"
    --query 'tasks[0].taskArn'
    --output text
  )

  if [ -n "${overrides}" ]; then
    run_task_args+=(--overrides "${overrides}")
  fi

  echo "${description} with task definition ${TASK_DEFINITION_ARN}..."
  LAST_TASK_ARN="$("${run_task_args[@]}")"

  [ -n "${LAST_TASK_ARN}" ] && [ "${LAST_TASK_ARN}" != "None" ] || fail "Failed to start the task in cluster ${CLUSTER_NAME}"

  echo "Task ARN: ${LAST_TASK_ARN}"

  aws_with_auth ecs wait tasks-stopped \
    --region "${REGION}" \
    --cluster "${CLUSTER_NAME}" \
    --tasks "${LAST_TASK_ARN}"

  LAST_TASK_EXIT_CODE="$(aws_with_auth ecs describe-tasks \
    --region "${REGION}" \
    --cluster "${CLUSTER_NAME}" \
    --tasks "${LAST_TASK_ARN}" \
    --query 'tasks[0].containers[0].exitCode' \
    --output text)"

  LAST_TASK_STOPPED_REASON="$(aws_with_auth ecs describe-tasks \
    --region "${REGION}" \
    --cluster "${CLUSTER_NAME}" \
    --tasks "${LAST_TASK_ARN}" \
    --query 'tasks[0].stoppedReason' \
    --output text)"

  LAST_TASK_CONTAINER_REASON="$(aws_with_auth ecs describe-tasks \
    --region "${REGION}" \
    --cluster "${CLUSTER_NAME}" \
    --tasks "${LAST_TASK_ARN}" \
    --query 'tasks[0].containers[0].reason' \
    --output text)"
}

has_pending_migrations() {
  local overrides
  local task_id

  overrides="$(build_task_overrides "set -eu; python manage.py showmigrations --plan --no-color > /tmp/migration-plan.txt; cat /tmp/migration-plan.txt; if grep -q '^\\[ \\]' /tmp/migration-plan.txt; then exit 10; fi")"

  run_ecs_task "Checking for pending Django migrations" "${overrides}"
  task_id="${LAST_TASK_ARN##*/}"

  case "${LAST_TASK_EXIT_CODE}" in
    0)
      echo "No pending Django migrations detected."
      return 1
      ;;
    10)
      echo "Pending Django migrations detected."
      return 0
      ;;
    *)
      print_task_logs "${task_id}"
      fail "Migration check task failed with exit code ${LAST_TASK_EXIT_CODE}. Stopped reason: ${LAST_TASK_STOPPED_REASON}. Container reason: ${LAST_TASK_CONTAINER_REASON}"
      ;;
  esac
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
      [ "${MIGRATION_START_DB_INSTANCE}" = "1" ] || fail "RDS instance ${db_instance_identifier} is stopped."
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
      fail "RDS instance ${db_instance_identifier} is not ready for migrations: ${db_status}"
      ;;
  esac
}

require_cmd aws
require_cmd mktemp
require_cmd python3
require_cmd tr

set_aws_auth_mode

NAME_PREFIX="${NAME_PREFIX:-${PROJECT_NAME}-${ENVIRONMENT}}"
CLUSTER_NAME="${ECS_CLUSTER_NAME:-${NAME_PREFIX}-cluster}"
TASK_DEFINITION="${MIGRATION_TASK_DEFINITION:-${NAME_PREFIX}-migration}"
MIGRATION_LOG_GROUP="${MIGRATION_LOG_GROUP:-/ecs/${NAME_PREFIX}/migration}"
API_SERVICE_NAME="${NAME_PREFIX}-api"

LAST_TASK_ARN=""
LAST_TASK_EXIT_CODE=""
LAST_TASK_STOPPED_REASON=""
LAST_TASK_CONTAINER_REASON=""

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

TASK_DEFINITION_ARN="$(resolve_task_definition_arn)"

IFS=$'\t \n,' read -r -a SUBNET_IDS <<< "${PUBLIC_SUBNET_IDS}"
[ "${#SUBNET_IDS[@]}" -gt 0 ] || fail "No public subnet IDs available for the migration task"

subnet_csv="$(IFS=,; echo "${SUBNET_IDS[*]}")"
network_configuration="awsvpcConfiguration={subnets=[${subnet_csv}],securityGroups=[${APP_SECURITY_GROUP_ID}],assignPublicIp=ENABLED}"

should_run_post_migration_task=0

if has_pending_migrations; then
  should_run_post_migration_task=1
fi

if [ "${ENSURE_SUPERUSER_AFTER_MIGRATION}" = "1" ]; then
  should_run_post_migration_task=1
fi

if [ "${SEED_DEMO_ACCOUNTS}" = "1" ]; then
  should_run_post_migration_task=1
fi

if [ "${should_run_post_migration_task}" != "1" ]; then
  echo "Django migrations skipped."
  exit 0
fi

run_ecs_task "Running Django post-deploy bootstrap" "$(build_task_overrides "$(build_post_migration_command)")"

if [ "${LAST_TASK_EXIT_CODE}" != "0" ]; then
  print_task_logs "${LAST_TASK_ARN##*/}"
  fail "Post-deploy bootstrap task failed with exit code ${LAST_TASK_EXIT_CODE}. Stopped reason: ${LAST_TASK_STOPPED_REASON}. Container reason: ${LAST_TASK_CONTAINER_REASON}"
fi

echo "Django post-deploy bootstrap completed successfully."
