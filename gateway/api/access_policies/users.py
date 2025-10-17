"""
Access policies implementation for Users access
"""

import logging
from django.contrib.auth.models import AbstractUser


logger = logging.getLogger("gateway")


class UserAccessPolicies:
    """
    The main objective of this class is to manage the access for the user
    to the application.
    """

    @staticmethod
    def can_access(user: type[AbstractUser]) -> bool:
        """
        Checks if the user has access to the application.
        For that, the user will need to be active.

        Args:
            user: Django user from the request

        Returns:
            bool: True or False in case the user has access
        """

        if user.is_active:
            return True

        logger.warning("User [%s] is not active.", user.username)
        return False
