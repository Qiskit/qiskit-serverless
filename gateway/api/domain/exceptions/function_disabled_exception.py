"""Function disabled exception."""

from api.domain.exceptions.not_found_exception import NotFoundError


class FunctionDisabledException(NotFoundError):
    """Exception raised when a Qiskit function is disabled."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)
