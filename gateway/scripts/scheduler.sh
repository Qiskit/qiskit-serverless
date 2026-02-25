#!/bin/sh

python manage.py migrate_with_lock
while :
do
  exec python manage.py update_jobs_statuses
  exec python manage.py free_resources
	exec python manage.py schedule_queued_jobs
	sleep 1
done
