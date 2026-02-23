"""Base exception for not found errors."""

from abc import ABC


class NotFoundError(Exception, ABC):
    """
    Abstract base exception for not found errors.

    Cannot be instantiated directly - use specific subclasses like:
    - JobNotFoundException
    - ProviderNotFoundException
    - FunctionNotFoundException
    - FileNotFoundException
    """

    def __init__(self, message: str):
        if type(self) is NotFoundError:
            raise TypeError("Cannot instantiate abstract class NotFoundError directly")
        self.message = message
        super().__init__(message)
