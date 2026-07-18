#!/bin/sh
set -eu

TUNNEL_FILE="${CLOUDFLARE_TUNNEL_URL_FILE:-/data/cloudflared/tunnel-url}"
WEBHOOK_PATH="${FLUTTERWAVE_WEBHOOK_PATH:-/api/v1/payments/webhook/flutterwave}"

echo "Waiting for Cloudflare tunnel URL..."

attempt=0
max_attempts="${CLOUDFLARE_WAIT_ATTEMPTS:-60}"

while [ ! -s "$TUNNEL_FILE" ]; do
  attempt=$((attempt + 1))

  if [ "$attempt" -ge "$max_attempts" ]; then
    echo "Error: Cloudflare tunnel URL was not available at $TUNNEL_FILE"
    exit 1
  fi

  sleep 1
done

CLOUDFLARE_TUNNEL_URL="$(
  tr -d '\r\n' < "$TUNNEL_FILE"
)"

case "$CLOUDFLARE_TUNNEL_URL" in
  https://*.trycloudflare.com)
    ;;
  *)
    echo "Error: Invalid Cloudflare Quick Tunnel URL:"
    echo "$CLOUDFLARE_TUNNEL_URL"
    exit 1
    ;;
esac

WEBHOOK_PATH="/${WEBHOOK_PATH#/}"

export CLOUDFLARE_TUNNEL_URL
export FLUTTERWAVE_WEBHOOK_URL="${CLOUDFLARE_TUNNEL_URL%/}${WEBHOOK_PATH}"

echo "Cloudflare tunnel URL: $CLOUDFLARE_TUNNEL_URL"
echo "Flutterwave webhook URL: $FLUTTERWAVE_WEBHOOK_URL"

exec /app/docker-entrypoint.sh "$@"
