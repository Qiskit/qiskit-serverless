"""
Configuration for the api application.
"""

from django.apps import AppConfig


class ApiConfig(AppConfig):
    """
    Application api configuration class.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "api"
