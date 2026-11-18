#!/bin/sh
set -eu

exec 2>&1

graceful_timeout="${GUNICORN_GRACEFUL_TIMEOUT:-30}"
stop_grace_period="${DOCKER_STOP_GRACE_PERIOD:-40s}"
case "$stop_grace_period" in
    *s) stop_grace_seconds="${stop_grace_period%s}" ;;
    *) stop_grace_seconds="" ;;
esac
case "$graceful_timeout" in
    ''|*[!0-9]*)
        echo "Gunicorn graceful timeout must be an integer number of seconds." >&2
        exit 64
        ;;
esac
case "$stop_grace_seconds" in
    ''|*[!0-9]*)
        echo "Docker stop grace must be integer seconds with an s suffix." >&2
        exit 64
        ;;
esac
if [ "$stop_grace_seconds" -le "$graceful_timeout" ]; then
    echo "Docker stop grace must be greater than the Gunicorn graceful timeout." >&2
    exit 64
fi

case "${SAFEPATH_RUN_MIGRATIONS:-false}" in
    true)
        python manage.py migrate --noinput
        ;;
    false)
        ;;
    *)
        echo "SAFEPATH_RUN_MIGRATIONS must be true or false." >&2
        exit 64
        ;;
esac

exec gunicorn --config gunicorn.conf.py safepath_backend.wsgi:application
