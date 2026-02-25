"""Applications."""

import logging

from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger("gateway")


class ApiConfig(AppConfig):
    """ApiConfig."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "api"
    is_ready = False

    def ready(self):
        """Executed when Gateway app starts"""

        # Import signal handlers only when Django has started and ready.
        import api.signals  # noqa: F401  # pylint: disable=import-outside-toplevel,unused-import

        # Flag used for the /liveness and /readiness probes
        ApiConfig.is_ready = True

        logger.info("**** api app started")
