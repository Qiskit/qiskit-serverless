#!/bin/sh

python manage.py migrate_with_lock
exec python manage.py scheduler_loop
