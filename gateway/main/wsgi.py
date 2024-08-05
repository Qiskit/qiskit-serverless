"""
WSGI config for gateway project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.1/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

application_mode = os.environ.get("APPLICATION_MODE", "api")
if application_mode == "api":
    django_settings_module = "main.settings_api"
elif application_mode == "scheduler":
    django_settings_module = "main.settings_scheduler"
elif application_mode == "admin_panel":
    django_settings_module = "main.settings_admin_panel"
else:
    django_settings_module = "main.settings_base"

os.environ.setdefault("DJANGO_SETTINGS_MODULE", django_settings_module)

application = get_wsgi_application()
