"""
Access policies implementation for Users access
"""

import logging
from django.contrib.auth.models import AbstractUser

logger = logging.getLogger("api.UserAccessPolicies")


class UserAccessPolicies:
    """
    The main objective of this class is to manage the access for the user
    to the application.
    """

    @staticmethod
    def can_access(user: AbstractUser) -> bool:
        """
        Checks if the user has access to the application.
        For that, the user will need to be active.

        Args:
            user: Django user from the request

        Returns:
            bool: True or False in case the user has access
        """

        if user is None:
            raise ValueError("user cannot be None")

        if user.is_active:
            return True

        logger.warning(
            "[can_access] user_id=%s | user inactive",
            user.id,
        )
        return False
