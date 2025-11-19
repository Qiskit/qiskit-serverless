"""Applications."""

from django.apps import AppConfig


class ApiConfig(AppConfig):
    """ApiConfig."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "api"

    def ready(self):
        """Import signal handlers when Django starts."""
        import api.signals  # noqa: F401
