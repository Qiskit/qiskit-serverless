"""Base exception for business domain errors."""

from django.conf import settings

from core.config_key import ConfigKey
from core.models import Config


class ActiveJobLimitExceeded(Exception):
    """Base exception for business domain errors."""

    def __init__(self, message: str = None):
        self.limit = Config.get_int_or(ConfigKey.ACTIVE_JOBS_PER_USER, settings.LIMITS_ACTIVE_JOBS_PER_USER)
        self.message = f"Active job limit reached. The maximum allowed is {self.limit}."
        super().__init__(message)
