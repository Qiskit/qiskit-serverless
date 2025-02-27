"""CustomTokenBackend."""

import logging
from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from rest_framework import authentication

from api.models import VIEW_PROGRAM_PERMISSION, RUN_PROGRAM_PERMISSION, Provider
from api.use_cases.authentication import AuthenticationUseCase


User = get_user_model()
logger = logging.getLogger("gateway.authentication")


@dataclass
class CustomToken:
    """CustomToken."""

    token: str


class CustomTokenBackend(authentication.BaseAuthentication):
    """Custom token backend for authentication against 3rd party auth service."""

    def authenticate(self, request):
        quantum_user = None
        authorization_token = None

        crn = request.META.get("HTTP_SERVICE_CRN", None)
        auth_header = request.META.get("HTTP_AUTHORIZATION")
        if auth_header is None:
            logger.warning(
                "Problems authenticating: user did not provide authorization token."
            )
            return quantum_user, authorization_token
        authorization_token = auth_header.split(" ")[-1]

        quantum_user = AuthenticationUseCase(
            authorization_token=authorization_token, crn=crn
        ).execute()
        if quantum_user is None:
            return quantum_user, CustomToken(authorization_token.encode())

        return quantum_user, CustomToken(authorization_token.encode())


class MockTokenBackend(authentication.BaseAuthentication):
    """Custom mock auth backend for tests."""

    def authenticate(self, request):
        user = None
        token = None

        auth_header = request.META.get("HTTP_AUTHORIZATION")
        if auth_header is not None:
            token = auth_header.split(" ")[-1]

            if settings.SETTINGS_AUTH_MOCK_TOKEN is not None:
                if token == settings.SETTINGS_AUTH_MOCK_TOKEN:
                    user, created = User.objects.get_or_create(username="mockuser")
                    if created:
                        logger.info("New user created")
                        view_program = Permission.objects.get(
                            codename=VIEW_PROGRAM_PERMISSION
                        )
                        run_program = Permission.objects.get(
                            codename=RUN_PROGRAM_PERMISSION
                        )
                        group, created = Group.objects.get_or_create(name="mockgroup")
                        group.permissions.add(view_program)
                        group.permissions.add(run_program)
                        group.user_set.add(user)
                        logger.info("New group created")
                        provider = Provider.objects.create(
                            name="mockprovider",
                            registry=settings.SETTINGS_AUTH_MOCKPROVIDER_REGISTRY,
                        )
                        provider.admin_groups.add(group)
                        logger.info("New provider created")

        return user, CustomToken(token.encode()) if token else None
