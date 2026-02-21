#!/bin/sh

python manage.py migrate_with_lock
python manage.py scheduler_loop
