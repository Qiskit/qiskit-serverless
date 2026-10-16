"""Base exception for business domain errors."""


class ActiveJobLimitExceeded(Exception):
    """Base exception for business domain errors."""

    def __init__(self, limit: int, message: str = None):
        self.limit = limit
        self.message = f"Active job limit reached. The maximum allowed is {self.limit}."
        super().__init__(message)
