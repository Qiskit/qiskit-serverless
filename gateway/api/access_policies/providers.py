"""
Access policies implementation for Provider access
"""
import logging

from api.models import Provider


logger = logging.getLogger("gateway")


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

        user_groups = set(user.groups.all())
        admin_groups = set(provider.admin_groups.all())
        user_is_admin = bool(user_groups.intersection(admin_groups))
        if not user_is_admin:
            logger.warning(
                "User [%s] has no access to provider [%s].", user.id, provider.name
            )
        return user_is_admin
