"""Engine unavailable exception."""


class EngineUnavailableException(Exception):
    """Exception raised when the compute engine could not carry out a request."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)
