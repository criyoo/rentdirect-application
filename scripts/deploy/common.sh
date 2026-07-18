#!/usr/bin/env bash
set -euo pipefail

PROJECT_NAME="rentdirect"
AWS_REGION="eu-west-1"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPLICATION_ROOT="${APPLICATION_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

API_DIR="$APPLICATION_ROOT/api"
WEB_DIR="$APPLICATION_ROOT/web"

fail() {
  echo "Error: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

set_environment_defaults() {
  ENVIRONMENT="${1:-dev}"
  export ENVIRONMENT

  if [[ "$ENVIRONMENT" == "prod" ]]; then
    WEB_DOMAIN="rentdirect.homes"
    API_DOMAIN="api.rentdirect.homes"
    MEDIA_DOMAIN="media.rentdirect.homes"
  elif [[ "$ENVIRONMENT" == "dev" ]]; then
    WEB_DOMAIN="development.rentdirect.homes"
    API_DOMAIN="api.development.rentdirect.homes"
    MEDIA_DOMAIN="media.development.rentdirect.homes"
  else
    WEB_DOMAIN="$ENVIRONMENT.rentdirect.homes"
    API_DOMAIN="api.$ENVIRONMENT.rentdirect.homes"
    MEDIA_DOMAIN="media.$ENVIRONMENT.rentdirect.homes"
  fi

  AWS_WORKLOAD_PROFILE="$ENVIRONMENT-$PROJECT_NAME"
  NAME_PREFIX="$PROJECT_NAME-$ENVIRONMENT"

  export WEB_DOMAIN API_DOMAIN MEDIA_DOMAIN AWS_REGION AWS_WORKLOAD_PROFILE NAME_PREFIX
}

set_aws_auth_mode() {
  export AWS_PAGER=""

  if [[ "${AWS_USE_PROFILE:-}" == "0" ]]; then
    AWS_PROFILE_ARGS=()
    return
  fi

  if [[ -n "${AWS_ACCESS_KEY_ID:-}" ||
        -n "${AWS_WEB_IDENTITY_TOKEN_FILE:-}" ||
        -n "${AWS_CONTAINER_CREDENTIALS_RELATIVE_URI:-}" ||
        -n "${AWS_CONTAINER_CREDENTIALS_FULL_URI:-}" ]]; then
    AWS_PROFILE_ARGS=()
    return
  fi

  unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
  unset AWS_SECURITY_TOKEN AWS_SESSION_EXPIRATION AWS_ACCESS_KEY AWS_SECRET_KEY

  AWS_PROFILE_ARGS=(--profile "$AWS_WORKLOAD_PROFILE")
}

aws_with_auth() {
  aws "${AWS_PROFILE_ARGS[@]}" "$@"
}

describe_app_service() {
  aws_with_auth ecs describe-services \
    --region "$AWS_REGION" \
    --cluster "$ECS_CLUSTER_NAME" \
    --services "$1" \
    --query 'services[0]' \
    --output json
}

service_exists() {
  [[ "$(describe_app_service "$1" \
    | python3 -c 'import json,sys; data=json.load(sys.stdin); print(data.get("status", "") if isinstance(data, dict) else "")')" == "ACTIVE" ]]
}

resolve_public_subnets() {
  [[ -n "${PUBLIC_SUBNET_IDS:-}" ]] && return

  PUBLIC_SUBNET_IDS="$(aws_with_auth ec2 describe-subnets \
    --region "$AWS_REGION" \
    --filters \
      "Name=tag:Project,Values=$PROJECT_NAME" \
      "Name=tag:Environment,Values=$ENVIRONMENT" \
      "Name=tag:Tier,Values=public" \
    --query 'Subnets[].SubnetId' \
    --output text)"

  [[ -n "$PUBLIC_SUBNET_IDS" && "$PUBLIC_SUBNET_IDS" != "None" ]] ||
    fail "Could not resolve public subnets."
}

resolve_app_security_group() {
  [[ -n "${APP_SECURITY_GROUP_ID:-}" ]] && return

  APP_SECURITY_GROUP_ID="$(aws_with_auth ec2 describe-security-groups \
    --region "$AWS_REGION" \
    --filters "Name=group-name,Values=$NAME_PREFIX-app" \
    --query 'SecurityGroups[0].GroupId' \
    --output text)"

  [[ -n "$APP_SECURITY_GROUP_ID" && "$APP_SECURITY_GROUP_ID" != "None" ]] ||
    fail "Could not resolve app security group."
}
