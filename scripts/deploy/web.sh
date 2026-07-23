#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

set_environment_defaults "${1:-dev}"
set_aws_auth_mode

[ -d "${WEB_DIR}" ] || fail "Missing web directory: ${WEB_DIR}"

INSTALL_DEPS="${INSTALL_DEPS:-1}"
BUILD_WEB="${BUILD_WEB:-1}"
INVALIDATE_CLOUDFRONT="${INVALIDATE_CLOUDFRONT:-1}"
INVALIDATE_ONLY="${INVALIDATE_ONLY:-0}"

invalidate_cloudfront() {
  local distribution_id

  distribution_id="$(aws_with_auth cloudfront list-distributions \
    --query "DistributionList.Items[?Aliases.Items!=null && contains(Aliases.Items, '${WEB_DOMAIN}')].Id | [0]" \
    --output text)"

  [ -n "${distribution_id}" ] && [ "${distribution_id}" != "None" ] || fail "Could not find CloudFront distribution for ${WEB_DOMAIN}."

  aws_with_auth cloudfront create-invalidation \
    --distribution-id "${distribution_id}" \
    --paths "/*" >/dev/null
}


if [ "${INVALIDATE_ONLY}" = "1" ]; then
  invalidate_cloudfront
  exit 0
fi

BUCKET_NAME="${BUCKET_NAME:-frontend-${NAME_PREFIX}}"

aws_with_auth s3api head-bucket --region "${AWS_REGION}" --bucket "${BUCKET_NAME}" >/dev/null 2>&1 \
  || fail "Web bucket not found: ${BUCKET_NAME}"

if [ "${BUILD_WEB}" = "1" ]; then
  require_cmd npm
  require_cmd node

  if [ "${INSTALL_DEPS}" = "1" ]; then
    (
      cd "${WEB_DIR}"
      npm ci
    )
    node "${APPLICATION_ROOT}/scripts/ensure-rollup-native.cjs" "${WEB_DIR}"
  fi

  (
    cd "${WEB_DIR}"
    VITE_API_URL="https://${API_DOMAIN}/api/v1" \
    VITE_MEDIA_URL="https://${MEDIA_DOMAIN}" \
    VITE_WS_URL="wss://${API_DOMAIN}" \
    npm run build
  )
fi

[ -d "${WEB_DIR}/dist" ] || fail "Vite build output not found."

aws_with_auth s3 sync "${WEB_DIR}/dist/" "s3://${BUCKET_NAME}/" --region "${AWS_REGION}" --delete

aws_with_auth s3 cp "${WEB_DIR}/dist/" "s3://${BUCKET_NAME}/" \
  --region "${AWS_REGION}" \
  --recursive \
  --exclude "*" \
  --include "*.html" \
  --cache-control "public,max-age=0,s-maxage=60,must-revalidate"

if [ -d "${WEB_DIR}/dist/assets" ]; then
  aws_with_auth s3 cp "${WEB_DIR}/dist/assets/" "s3://${BUCKET_NAME}/assets/" \
    --region "${AWS_REGION}" \
    --recursive \
    --cache-control "public,max-age=31536000,immutable"
fi

if [ "${INVALIDATE_CLOUDFRONT}" = "1" ]; then
  invalidate_cloudfront
fi
