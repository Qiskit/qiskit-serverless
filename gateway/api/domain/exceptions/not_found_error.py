"""Base exception for business domain errors."""


class NotFoundError(Exception):
    """Base exception for business domain errors."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)
