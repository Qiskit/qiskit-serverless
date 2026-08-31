"""Function configuration exception."""


class FunctionConfigurationException(Exception):
    """Exception raised when a Qiskit function's configuration is invalid or incomplete."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)
