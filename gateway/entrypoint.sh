#!/bin/sh

python manage.py collectstatic --noinput
python manage.py migrate
python manage.py createsuperuser --noinput

python manage.py create_social_application --host="$SITE_HOST" --client_id="$CLIENT_ID"

exec "$@"
