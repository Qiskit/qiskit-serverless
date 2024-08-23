"""Applications."""

from django.apps import AppConfig
from django.db.models.signals import post_migrate

class ApiConfig(AppConfig):
    """ApiConfig."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "api"
