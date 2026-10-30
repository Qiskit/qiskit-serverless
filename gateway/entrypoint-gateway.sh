#!/bin/sh

python manage.py collectstatic --noinput
python manage.py migrate_with_lock --lock-timeout 900 || exit 1
python manage.py createsuperuser --noinput || true

exec "$@"
