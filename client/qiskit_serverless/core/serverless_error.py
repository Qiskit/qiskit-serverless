class ServerlessError(Exception):
    """Base exception that can be used by function developers."""

    def __init__(self, code: str, message: str, details: any):
        self.code = code
        self.message = message
        self.details = details
        super().__init__(self.message)

    def __str__(self):
        return f"[{self.code}] {self.message}\n{self.details}"
