#!/bin/sh

python manage.py migrate_with_lock || exit 1

exec python manage.py run_scheduler