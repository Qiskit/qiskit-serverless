"""
Custom exceptions for the gateway application
"""

from rest_framework import status


class GatewayException(Exception):
    """
    Generic custom exception for our application
    """

    def __init__(self, message):
        super().__init__(message)


class GatewayHttpException(GatewayException):
    """
    Generic http custom exception for our application
    """

    def __init__(self, message, http_code):
        super().__init__(message)
        self.http_code = http_code


class InternalServerErrorException(GatewayHttpException):
    """
    A wrapper for when we want to raise an internal server error
    """

    def __init__(self, message, http_code=status.HTTP_500_INTERNAL_SERVER_ERROR):
        super().__init__(message, http_code)


class ResourceNotFoundException(GatewayHttpException):
    """
    A wrapper for when we want to raise a 404 error
    """

    def __init__(self, message, http_code=status.HTTP_404_NOT_FOUND):
        super().__init__(message, http_code)
