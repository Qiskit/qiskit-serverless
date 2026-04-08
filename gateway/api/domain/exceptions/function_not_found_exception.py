"""Function not found exception."""

from typing import Optional
from api.domain.exceptions.not_found_exception import NotFoundError


class FunctionNotFoundException(NotFoundError):
    """Exception raised when a Qiskit function is not found."""

    def __init__(self, function: str, provider: Optional[str] = None):
        self.function = function
        self.provider = provider
        if provider:
            message = f"Qiskit Function {provider}/{function} doesn't exist."
        else:
            message = f"Qiskit Function {function} doesn't exist."
        super().__init__(message)
