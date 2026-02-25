#!/bin/sh
trap 'exit 0' TERM INT

python manage.py migrate_with_lock
while :
do
  python manage.py update_jobs_statuses
  python manage.py free_resources
  python manage.py schedule_queued_jobs
  sleep 1
done
