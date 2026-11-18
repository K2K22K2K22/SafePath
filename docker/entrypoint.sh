#!/bin/sh
set -eu

if [ "${SAFEPATH_RUN_MIGRATIONS:-false}" = "true" ]; then
    python manage.py migrate --noinput
fi

exec gunicorn --config gunicorn.conf.py safepath_backend.wsgi:application
