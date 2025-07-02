"""Custom Authentication DRF Backends to authenticate the user."""

import logging
from rest_framework import authentication, exceptions

from api.domain.authentication.custom_authentication import CustomAuthentication
from api.use_cases.authentication import AuthenticationUseCase
from api.domain.authentication.channel import Channel


logger = logging.getLogger("gateway.authentication")
PUBLIC_ENDPOINTS = ["catalog", "swagger"]

# This logic needs to be reviewed as it can be simplified
# maybe with isAuthenticatedOrReadOnly permission
def is_public_endpoint(path: str) -> bool:
    """
    This method checks if the path from the request is considered
    a valid public path or it requires authentication.

    Args:
        path (str): path from the request being processed

    Returns:
        bool: if the path is considered public or not
    """
    return any(public_path in path for public_path in PUBLIC_ENDPOINTS)


class CustomTokenBackend(authentication.BaseAuthentication):
    """Custom token backend for authentication against 3rd party auth service."""

    def authenticate(self, request):
        quantum_user = None
        authorization_token = None

        crn = request.META.get("HTTP_SERVICE_CRN", None)
        channel_header = request.META.get("HTTP_SERVICE_CHANNEL", None)
        if channel_header is None:
            # this is to maintain compatibility for older versions
            # that are not being managing channel
            channel_header = Channel.IBM_QUANTUM.value
        try:
            channel = Channel(channel_header)
        except ValueError as error:
            logger.warning("Channel value [%s] is not valid.", channel_header)
            raise exceptions.AuthenticationFailed(
                "The value of the channel is not correct. Verify that you are using one of these: "
                f"{Channel.IBM_QUANTUM.value}, {Channel.IBM_CLOUD.value}, "
                f"{Channel.IBM_QUANTUM_PLATFORM.value}"
            ) from error

        # Specific logic to guarantee access to public end-points
        public_access = False
        if is_public_endpoint(request.path):
            public_access = True

        auth_header = request.META.get("HTTP_AUTHORIZATION")
        if auth_header is None:
            if public_access:
                logger.debug(
                    "Authorization token was not provided. Only public access allowed."
                )
                return None, None
            logger.warning("Authorization token was not provided.")
            raise exceptions.AuthenticationFailed(
                "Authorization token was not provided."
            )
        authorization_token = auth_header.split(" ")[-1]

        quantum_user = AuthenticationUseCase(
            channel=channel,
            authorization_token=authorization_token,
            crn=crn,
            public_access=public_access,
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

        # Specific logic to guarantee access to public end-points
        public_access = False
        if is_public_endpoint(request.path):
            public_access = True

        auth_header = request.META.get("HTTP_AUTHORIZATION")
        if auth_header is None:
            if public_access:
                logger.debug(
                    "Authorization token was not provided. Only public access allowed."
                )
                return None, None
            logger.warning("Authorization token was not provided.")
            raise exceptions.AuthenticationFailed(
                "Authorization token was not provided."
            )
        authorization_token = auth_header.split(" ")[-1]

        quantum_user = AuthenticationUseCase(
            channel=channel,
            authorization_token=authorization_token,
            crn=None,
            public_access=public_access,
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
