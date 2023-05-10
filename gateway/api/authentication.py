"""CustomTokenBackend."""

import json
import logging
from dataclasses import dataclass

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import authentication

User = get_user_model()


@dataclass
class CustomToken:
    """CustomToken."""

    token: str


class CustomTokenBackend(authentication.BaseAuthentication):
    """Custom token backend for authentication against 3rd party auth service."""

    def authenticate(self, request):
        auth_url = settings.SETTINGS_TOKEN_AUTH_URL
        auth_header = request.META.get("HTTP_AUTHORIZATION")

        user = None
        token = None
        if auth_header is not None and auth_url is not None:
            token = auth_header.split(" ")[-1]

            response = requests.post(auth_url, json={"apiToken": token}, timeout=60)
            if response.ok:
                try:
                    json_response = json.loads(response.text)
                    user_id = json_response.get(settings.SETTINGS_TOKEN_AUTH_USER_FIELD)
                except ValueError as exception:
                    logging.error(
                        "Encountered exception on parsing response from %s", exception
                    )
                    user_id = None

                if user_id is not None:
                    try:
                        user = User.objects.get(username=user_id)
                    except User.DoesNotExist:
                        user = User(username=user_id)
                        user.save()

        return user, CustomToken(token.encode()) if token else None
