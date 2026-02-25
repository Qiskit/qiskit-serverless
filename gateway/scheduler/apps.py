"""Django app configuration for the scheduler module."""

import logging

from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger("scheduler")


class SchedulerConfig(AppConfig):
    """Configuration class for the scheduler Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "scheduler"
    is_ready = False

    def ready(self):
        """Executed when the Scheduler starts"""
        assert (
            settings.IS_SCHEDULER or settings.IS_TEST
        ), "SchedulerConfig.ready() executed but IS_SCHEDULER/IS_TEST are false"

        # Flag used for the /liveness and /readiness probes
        SchedulerConfig.is_ready = True

        logger.info("**** scheduler app started ****")
