"""Custom Authentication DRF Backends to authenticate the user."""

import logging
from rest_framework import authentication

from api.domain.authentication.custom_authentication import CustomAuthentication
from api.use_cases.authentication import AuthenticationUseCase
from api.domain.authentication.channel import Channel


logger = logging.getLogger("gateway.authentication")


class CustomTokenBackend(authentication.BaseAuthentication):
    """Custom token backend for authentication against 3rd party auth service."""

    def authenticate(self, request):
        channel = Channel.IBM_QUANTUM
        quantum_user = None
        authorization_token = None

        crn = request.META.get("HTTP_SERVICE_CRN", None)
        if crn is not None:
            channel = Channel.IBM_CLOUD

        auth_header = request.META.get("HTTP_AUTHORIZATION")
        if auth_header is None:
            logger.debug(
                "Authorization token was not provided. Only public access allowed."
            )
            return None, None
        authorization_token = auth_header.split(" ")[-1]

        quantum_user = AuthenticationUseCase(
            channel=channel, authorization_token=authorization_token, crn=crn
        ).execute()

        return quantum_user, CustomAuthentication(
            channel=channel, token=authorization_token.encode(), instance=crn
        )

    def authenticate_header(self, request):
        """
        This method is needed to returna 401 when the authentication fails.

        It setups the WWW-Authenticate header with the value Bearer to identify
        that we are using Bearer <token> as way to authenticate the user.
        """
        return "Bearer"


class MockTokenBackend(authentication.BaseAuthentication):
    """Custom mock auth backend for tests."""

    def authenticate(self, request):
        channel = Channel.LOCAL
        quantum_user = None
        authorization_token = None

        auth_header = request.META.get("HTTP_AUTHORIZATION")
        if auth_header is None:
            logger.debug(
                "Authorization token was not provided. Only public access allowed."
            )
            return None, None
        authorization_token = auth_header.split(" ")[-1]

        quantum_user = AuthenticationUseCase(
            channel=channel, authorization_token=authorization_token, crn=None
        ).execute()

        return quantum_user, CustomAuthentication(
            channel=channel, token=authorization_token.encode(), instance=None
        )

    def authenticate_header(self, request):
        """
        This method is needed to returna 401 when the authentication fails.

        It setups the WWW-Authenticate header with the value Bearer to identify
        that we are using Bearer <token> as way to authenticate the user.
        """
        return "Bearer"
