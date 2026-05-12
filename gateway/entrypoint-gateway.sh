#!/bin/sh

python manage.py collectstatic --noinput
python manage.py migrate_with_lock
python manage.py sync_ce_project
python manage.py createsuperuser --noinput

exec "$@"