"""Django app configuration for the scheduler module."""

from django.apps import AppConfig


class SchedulerConfig(AppConfig):
    """Configuration class for the scheduler Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "scheduler"
