#!/bin/sh

while :
do
  python manage.py update_jobs_statuses
  python manage.py free_resources
	python manage.py schedule_queued_jobs
	sleep 1
done
