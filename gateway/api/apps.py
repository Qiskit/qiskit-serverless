"""Applications."""

from django.apps import AppConfig


class ApiConfig(AppConfig):
    """ApiConfig."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "api"

    def ready(self):
        """Import signal handlers only when Django has started and ready."""
        import api.signals  # noqa: F401  # pylint: disable=import-outside-toplevel,unused-import
