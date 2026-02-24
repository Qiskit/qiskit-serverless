"""Base exception for business domain errors."""

from django.conf import settings


class ActiveJobLimitExceeded(Exception):
    """Base exception for business domain errors."""

    def __init__(self, message: str = None):
        self.limit = settings.LIMITS_ACTIVE_JOBS_PER_USER
        self.message = f"Active job limit reached. The maximum allowed is {self.limit}."
        super().__init__(message)
