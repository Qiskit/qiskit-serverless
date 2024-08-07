"""
ASGI config for gateway project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.1/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

application_mode = os.environ.get("APPLICATION_MODE", "api")
if application_mode == "api":
    DJANGO_SETTINGS_MODULE = "main.settings_api"
elif application_mode == "scheduler":
    DJANGO_SETTINGS_MODULE = "main.settings_scheduler"
elif application_mode == "admin_panel":
    DJANGO_SETTINGS_MODULE = "main.settings_admin_panel"
else:
    DJANGO_SETTINGS_MODULE = "main.settings_base"

os.environ.setdefault("DJANGO_SETTINGS_MODULE", DJANGO_SETTINGS_MODULE)

application = get_asgi_application()
