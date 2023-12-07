#!/bin/sh

python manage.py collectstatic --noinput
python manage.py migrate
python manage.py createsuperuser --noinput

exec "$@"
