"""
Access policies implementation for Provider access
"""

import logging

from core.models import Provider

logger = logging.getLogger("api.ProviderAccessPolicy")


class ProviderAccessPolicy:
    """
    The main objective of this class is to manage the access for the user
    to the Provider entities.
    """

    @staticmethod
    def can_access(user, provider: Provider) -> bool:
        """
        Checks if the user has access to a Provider:

        Args:
            user: Django user from the request
            provider: Provider instance against to check the access

        Returns:
            bool: True or False in case the user has access
        """
        if provider is None:
            raise ValueError("provider cannot be None")

        user_groups = set(user.groups.all())
        admin_groups = set(provider.admin_groups.all())
        user_is_admin = bool(user_groups.intersection(admin_groups))
        if not user_is_admin:
            logger.warning(
                "[can_access] provider=%s user_id=%s | no access",
                provider.name,
                user.id,
            )
        return user_is_admin
