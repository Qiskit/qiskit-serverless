#!/bin/sh

python manage.py migrate_with_lock --lock-timeout 900 || exit 1

exec python manage.py run_scheduler
