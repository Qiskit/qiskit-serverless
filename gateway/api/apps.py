"""Applications."""

from django.apps import AppConfig


class ApiConfig(AppConfig):
    """ApiConfig."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "api"

    def ready(self):
        import api.signals  # pylint: disable=unused-import,import-outside-toplevel
