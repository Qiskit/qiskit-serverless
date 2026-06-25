"""Function disabled exception."""


class FunctionDisabledException(Exception):
    """Exception raised when a Qiskit function is disabled."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)
