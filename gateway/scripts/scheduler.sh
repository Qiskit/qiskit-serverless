#!/bin/sh

until python manage.py migrate --check; do
    echo "Waiting for migrations to be applied..."
    sleep 1
done

exec python manage.py run_scheduler
