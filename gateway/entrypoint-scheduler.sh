#!/bin/sh

python manage.py migrate_with_lock
python manage.py sync_ce_project

exec python manage.py run_scheduler