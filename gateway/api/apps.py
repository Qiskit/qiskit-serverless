"""Applications."""

from django.apps import AppConfig


class ApiConfig(AppConfig):
    """ApiConfig."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "api"
    is_ready = False

    def ready(self):
        """Import signal handlers only when Django has started and ready."""
        import api.signals  # noqa: F401  # pylint: disable=import-outside-toplevel,unused-import
        from main.tracing import setup_gateway_tracing  # pylint: disable=import-outside-toplevel

        setup_gateway_tracing()
        ApiConfig.is_ready = True
