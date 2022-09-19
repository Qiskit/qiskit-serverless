"""Errors definition"""


class CommandError(Exception):
    """Encapsulates error coming from shell commands."""


class ValidationError(Exception):
    """Encapsulates data validation errors."""


class NotFoundError(Exception):
    """Encapsulates not found error."""


class ConfigurationError(Exception):
    """Application not properly configured"""
