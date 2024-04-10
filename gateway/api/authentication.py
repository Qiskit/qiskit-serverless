"""CustomTokenBackend."""

import logging
from dataclasses import dataclass

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import authentication

from api.utils import safe_request


User = get_user_model()
logger = logging.getLogger("gateway")


@dataclass
class CustomToken:
    """CustomToken."""

    token: str


class CustomTokenBackend(authentication.BaseAuthentication):
    """Custom token backend for authentication against 3rd party auth service."""

    def authenticate(self, request):  # pylint: disable=too-many-branches
        auth_url = settings.SETTINGS_TOKEN_AUTH_URL
        verification_url = settings.SETTINGS_TOKEN_AUTH_VERIFICATION_URL
        auth_header = request.META.get("HTTP_AUTHORIZATION")

        user = None
        token = None
        if auth_header is not None and auth_url is not None:
            token = auth_header.split(" ")[-1]

            auth_data = safe_request(
                request=lambda: requests.post(
                    auth_url,
                    json={settings.SETTINGS_TOKEN_AUTH_TOKEN_FIELD: token},
                    timeout=60,
                )
            )
            if auth_data is not None:
                user_id = auth_data.get(settings.SETTINGS_TOKEN_AUTH_USER_FIELD)

                verification_data = safe_request(
                    request=lambda: requests.get(
                        verification_url,
                        headers={"Authorization": auth_data.get("id")},
                        timeout=60,
                    )
                )

                if verification_data is not None:
                    verifications = []
                    for (
                        verification_field
                    ) in settings.SETTINGS_TOKEN_AUTH_VERIFICATION_FIELD.split(";"):
                        nested_field_value = verification_data
                        for nested_field in verification_field.split(","):
                            nested_field_value = nested_field_value.get(nested_field)
                        verifications.append(nested_field_value)

                    verified = all(verifications)

                    if user_id is not None and verified:
                        try:
                            user = User.objects.get(username=user_id)
                        except User.DoesNotExist:
                            user = User(username=user_id)
                            user.save()
                    elif user_id is None:
                        logger.warning("Problems authenticating: No user id.")
                    else:  # not verified
                        logger.warning("Problems authenticating: User is not verified.")

                else:  # verification_data is None
                    logger.warning(
                        "Problems authenticating: No verification data returned from request."
                    )

            else:  # auth_data is None
                logger.warning(
                    "Problems authenticating: No authorization data returned from auth url."
                )

        elif auth_header is None:
            logger.warning(
                "Problems authenticating: User did not provide authorization token."
            )
        else:  # auth_url is None
            logger.warning(
                "Problems authenticating: No auth url: something is broken in our settings."
            )

        return user, CustomToken(token.encode()) if token else None


class MockAuthBackend(authentication.BaseAuthentication):
    """Custom mock auth backend for tests."""

    def authenticate(self, request):
        user = None
        token = None

        auth_header = request.META.get("HTTP_AUTHORIZATION")
        if auth_header is not None:
            token = auth_header.split(" ")[-1]

            if settings.SETTINGS_AUTH_MOCK_TOKEN is not None:
                if token == settings.SETTINGS_AUTH_MOCK_TOKEN:
                    try:
                        user = User.objects.get(username="mockuser")
                    except User.DoesNotExist:
                        user = User(username="mockuser")
                        user.save()

        return user, CustomToken(token.encode()) if token else None
