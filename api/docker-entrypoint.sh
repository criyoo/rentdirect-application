#!/bin/sh
set -eu

should_prepare=0

case "${1:-}" in
  gunicorn|uvicorn)
    should_prepare=1
    ;;
  python|python3)
    if [ "${2:-}" = "manage.py" ] && [ "${3:-}" = "runserver" ]; then
      should_prepare=1
    fi
    ;;
esac

if [ "$should_prepare" = "1" ] && [ "${MIGRATE_ON_STARTUP:-0}" = "1" ]; then
  python manage.py migrate --noinput
fi

seed_on_startup="${SEED_DEMO_ACCOUNTS_ON_STARTUP:-${SEED_DEMO_ACCOUNTS:-0}}"
if [ "$should_prepare" = "1" ] && [ "$seed_on_startup" = "1" ]; then
  python manage.py seed_demo_data
fi

if [ "$should_prepare" = "1" ] && [ "${COLLECTSTATIC_ON_STARTUP:-1}" = "1" ]; then
  python manage.py collectstatic --noinput
fi

if [ "$should_prepare" = "1" ] && [ "${SEED_DEMO_ACCOUNTS_WATCH:-0}" = "1" ]; then
  python /app/scripts/seed_watch.py &
fi

if [ "$should_prepare" = "1" ] && [ "${RENEWAL_REMINDER_WATCH:-0}" = "1" ]; then
  python /app/scripts/renewal_reminder_watch.py &
fi

exec "$@"
