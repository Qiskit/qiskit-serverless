"""CustomTokenBackend."""

import logging
from dataclasses import dataclass
from rest_framework import authentication

from api.use_cases.authentication import AuthenticationUseCase
from api.use_cases.enums.channel import Channel


logger = logging.getLogger("gateway.authentication")


@dataclass
class CustomToken:
    """CustomToken."""

    token: str


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
            logger.warning(
                "Problems authenticating: user did not provide authorization token."
            )
            return quantum_user, authorization_token
        authorization_token = auth_header.split(" ")[-1]

        quantum_user = AuthenticationUseCase(
            channel=channel, authorization_token=authorization_token, crn=crn
        ).execute()
        if quantum_user is None:
            return quantum_user, CustomToken(authorization_token.encode())

        return quantum_user, CustomToken(authorization_token.encode())


class MockTokenBackend(authentication.BaseAuthentication):
    """Custom mock auth backend for tests."""

    def authenticate(self, request):
        channel = Channel.LOCAL
        quantum_user = None
        authorization_token = None

        auth_header = request.META.get("HTTP_AUTHORIZATION")
        if auth_header is None:
            logger.warning(
                "Problems authenticating: user did not provide authorization token."
            )
            return quantum_user, authorization_token
        authorization_token = auth_header.split(" ")[-1]

        quantum_user = AuthenticationUseCase(
            channel=channel, authorization_token=authorization_token, crn=None
        ).execute()
        if quantum_user is None:
            return quantum_user, CustomToken(authorization_token.encode())

        return quantum_user, CustomToken(authorization_token.encode())
