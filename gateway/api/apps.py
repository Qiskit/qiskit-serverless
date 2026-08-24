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
        from api.domain.arguments_schema import max_arguments_length  # pylint: disable=import-outside-toplevel
        from main.tracing import setup_gateway_tracing  # pylint: disable=import-outside-toplevel

        # Raises ImproperlyConfigured if MAX_ARGUMENTS_LENGTH_MB is above what the code allows, so a
        # bad value stops the boot instead of surfacing on the first request that validates arguments.
        max_arguments_length()

        setup_gateway_tracing()
        ApiConfig.is_ready = True
