"""This service will manage the access for local developments."""

import logging
from typing import List, Optional

from django.conf import settings
from rest_framework import exceptions

from api.domain.authentication.authentication_group import AuthenticationGroup
from api.services.authentication.authentication_base import AuthenticationBase


logger = logging.getLogger("gateway.services.authentication.local_authentication")


class LocalAuthenticationService(AuthenticationBase):
    """
    This class will implement the abstract methods to authenticate
    locally from the authentication interface.
    """

    def __init__(self, authorization_token: str):
        self.authorization_token = authorization_token
        self.username = "mockuser"

    def authenticate(self) -> Optional[str]:
        """
        This method authenticates verifies if the token is the
        correct one.

        Ideally this method should be called first.

        Returns:
            str: the user_id of the authenticated user
            None: in case the authentication failed
        """
        if settings.SETTINGS_AUTH_MOCK_TOKEN is None:
            logger.warning("Mock token environment variable is not configured.")
            raise exceptions.AuthenticationFailed(
                "Mock token environment variable is not configured."
            )

        if self.authorization_token != settings.SETTINGS_AUTH_MOCK_TOKEN:
            logger.warning("Authorization token and mock token are different.")
            raise exceptions.AuthenticationFailed("Authorization token is not valid.")

        return self.username

    def verify_access(self) -> bool:
        """
        Locally there is no verification needed so this method always return True.

        Returns:
            bool: True or False if the user has or no access
        """
        return True

    def get_groups(self) -> List[AuthenticationGroup]:
        """
        Locally there is only one group called mockgroup.

        Returns:
            List of groups
        """
        return [AuthenticationGroup(group_name="mockgroup")]
