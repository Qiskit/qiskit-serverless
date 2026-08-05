"""Invalid arguments exception."""


class InvalidArgumentsException(Exception):
    """Exception raised when job arguments fail JSON decoding or schema validation."""

    def __init__(self, message: str, path: list = None):
        self.message = message
        self.path = path if path is not None else []
        super().__init__(message)
