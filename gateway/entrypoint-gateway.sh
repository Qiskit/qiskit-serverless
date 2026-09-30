#!/bin/sh

python manage.py collectstatic --noinput
python manage.py migrate_with_lock || exit 1
python manage.py createsuperuser --noinput || true

exec "$@"