from rest_framework import status

class GatewayException(Exception):
    def __init__(self, message):
        super().__init__(message)


class GatewayHttpException(GatewayException):
    def __init__(self, message, http_code):
        super().__init__(message)
        self.http_code = http_code
    
class InternalServerErrorException(GatewayHttpException):
    def __init__(self, message):
        super().__init__(message)
        self.http_code = status.HTTP_500_INTERNAL_SERVER_ERROR
