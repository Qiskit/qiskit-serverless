#!/bin/sh
trap 'exit 0' TERM INT

python manage.py migrate_with_lock
exec python manage.py scheduler_loop
