"""Runtime function exceptions."""


class RuntimeApiException(Exception):
    """Error in Runtime API"""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class RuntimeFunctionsException(RuntimeApiException):
    """Error in Runtime API /functions"""
