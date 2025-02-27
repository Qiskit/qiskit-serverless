"""This service will manage the access for local developments."""

import logging
from typing import List

from django.conf import settings

from api.services.authentication.authentication_base import AuthenticationBase


logger = logging.getLogger("gateway.services.authentication.local_authentication")


class LocalAuthenticationService(AuthenticationBase):
    """
    This class will implement the abstract methods to authenticate
    locally from the authentication interface.
    """

    def __init__(self, authorization_token: str):
        self.authorization_token = authorization_token
        self.username="mockuser"

    def authenticate(self) -> str | None:
        """
        This method authenticates verifies if the token is the
        correct one.

        Ideally this method should be called first.

        Returns:
            str: the user_id of the authenticated user
            None: in case the authentication failed
        """
        if settings.SETTINGS_AUTH_MOCK_TOKEN is None:
            logger.warning(
                "Problems authenticating: mock token is not configured."
            )
            return None
        
        if self.authorization_token != settings.SETTINGS_AUTH_MOCK_TOKEN:
            logger.warning(
                "Problems authenticating: authorization token and mock token are different."
            )
            return None
        
        return self.username
    
    def verify_access(self) -> bool:
        """
        Locally there is no verification needed so this method always return True.

        Returns:
            bool: True or False if the user has or no access
        """
        return True
    
    def get_groups(self) -> List[str]:
        """
        Locally there is only one group called mockgroup.

        Returns:
            List of groups
        """
        return ["mockgroup"]
