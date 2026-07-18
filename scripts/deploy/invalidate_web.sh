#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENVIRONMENT="${1:-dev}"

INVALIDATE_ONLY=1 bash "${SCRIPT_DIR}/web.sh" "${ENVIRONMENT}"
