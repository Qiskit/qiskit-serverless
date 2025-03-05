"""CustomTokenBackend."""

import logging
from dataclasses import dataclass
from typing import Optional
from rest_framework import authentication, exceptions

from api.use_cases.authentication import AuthenticationUseCase
from api.use_cases.enums.channel import Channel


logger = logging.getLogger("gateway.authentication")


@dataclass
class CustomAuthentication:
    """CustomToken."""

    channel: Channel
    token: str
    instance: Optional[str]


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
                "Authorization token was not provided."
            )
            raise exceptions.AuthenticationFailed("Authorization token was not provided.")
        authorization_token = auth_header.split(" ")[-1]

        quantum_user = AuthenticationUseCase(
            channel=channel, authorization_token=authorization_token, crn=crn
        ).execute()

        return quantum_user, CustomAuthentication(
            channel=channel, token=authorization_token.encode(), instance=crn
        )


class MockTokenBackend(authentication.BaseAuthentication):
    """Custom mock auth backend for tests."""

    def authenticate(self, request):
        channel = Channel.LOCAL
        quantum_user = None
        authorization_token = None

        auth_header = request.META.get("HTTP_AUTHORIZATION")
        if auth_header is None:
            logger.warning(
                "Authorization token was not provided."
            )
            raise exceptions.AuthenticationFailed("Authorization token was not provided.")
        authorization_token = auth_header.split(" ")[-1]

        quantum_user = AuthenticationUseCase(
            channel=channel, authorization_token=authorization_token, crn=None
        ).execute()

        return quantum_user, CustomAuthentication(
            channel=channel, token=authorization_token.encode(), instance=None
        )
