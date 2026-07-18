#!/usr/bin/env bash

set -euo pipefail

ENVIRONMENT="${1:-dev}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

set_environment_defaults "$ENVIRONMENT"
set_aws_auth_mode
require_cmd docker
require_cmd python3

[ -d "${API_DIR}" ] || fail "Missing API directory: ${API_DIR}"

DEPLOY_ECS="${DEPLOY_ECS:-1}"
RUN_MIGRATIONS="${RUN_MIGRATIONS:-1}"
WAIT_FOR_STABLE="${WAIT_FOR_STABLE:-1}"
API_DESIRED_COUNT="${API_DESIRED_COUNT:-1}"
BUILDER_NAME="${BUILDER_NAME:-rentdirect-multiarch}"
DOCKER_PLATFORM="linux/arm64"
ECS_CLUSTER_NAME="${NAME_PREFIX}-cluster"
ECR_REPOSITORY_NAME="${NAME_PREFIX}-api"

REPOSITORY_URI="$(aws_with_auth ecr describe-repositories \
  --region "${AWS_REGION}" \
  --repository-names "${ECR_REPOSITORY_NAME}" \
  --query 'repositories[0].repositoryUri' \
  --output text)"

[ -n "${REPOSITORY_URI}" ] && [ "${REPOSITORY_URI}" != "None" ] || fail "Could not resolve ECR repository ${ECR_REPOSITORY_NAME}."

aws_with_auth ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${REPOSITORY_URI%%/*}" >/dev/null

docker buildx inspect "${BUILDER_NAME}" >/dev/null 2>&1 || docker buildx create --name "${BUILDER_NAME}" --driver docker-container --use >/dev/null
docker buildx use "${BUILDER_NAME}" >/dev/null
docker buildx inspect --bootstrap "${BUILDER_NAME}" >/dev/null

docker buildx build \
  --builder "${BUILDER_NAME}" \
  --platform "${DOCKER_PLATFORM}" \
  --cache-from type=registry,ref="${REPOSITORY_URI}:buildcache" \
  --cache-to type=registry,ref="${REPOSITORY_URI}:buildcache",mode=max,oci-mediatypes=true,image-manifest=true \
  --provenance=false \
  --sbom=false \
  --tag "${REPOSITORY_URI}:${ENVIRONMENT}" \
  --push \
  "${API_DIR}"

if [ "${DEPLOY_ECS}" != "1" ]; then
  exit 0
fi

if [ "${RUN_MIGRATIONS}" = "1" ]; then
  export DEPLOY_IMAGE_URI="${REPOSITORY_URI}:${ENVIRONMENT}"
  bash "${APPLICATION_ROOT}/scripts/migrate.sh" "${ENVIRONMENT}"
fi

services=("${NAME_PREFIX}-api" "${NAME_PREFIX}-worker")
deployed_services=()

for service_name in "${services[@]}"; do
  if ! service_exists "${service_name}"; then
    continue
  fi

  desired_count="$(aws_with_auth ecs describe-services \
    --region "${AWS_REGION}" \
    --cluster "${ECS_CLUSTER_NAME}" \
    --services "${service_name}" \
    --query 'services[0].desiredCount' \
    --output text)"

  if [ "${service_name}" = "${NAME_PREFIX}-api" ] && [ "${desired_count}" = "0" ] && [ "${API_DESIRED_COUNT}" -gt 0 ]; then
    aws_with_auth ecs update-service \
      --region "${AWS_REGION}" \
      --cluster "${ECS_CLUSTER_NAME}" \
      --service "${service_name}" \
      --desired-count "${API_DESIRED_COUNT}" \
      --force-new-deployment >/dev/null
  else
    aws_with_auth ecs update-service \
      --region "${AWS_REGION}" \
      --cluster "${ECS_CLUSTER_NAME}" \
      --service "${service_name}" \
      --force-new-deployment >/dev/null
  fi

  deployed_services+=("${service_name}")
done

if [ "${WAIT_FOR_STABLE}" = "1" ] && [ "${#deployed_services[@]}" -gt 0 ]; then
  aws_with_auth ecs wait services-stable \
    --region "${AWS_REGION}" \
    --cluster "${ECS_CLUSTER_NAME}" \
    --services "${deployed_services[@]}"
fi
