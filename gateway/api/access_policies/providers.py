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

        user_groups = user.groups.all()
        admin_groups = provider.admin_groups.all()
        has_access = any(group in admin_groups for group in user_groups)
        if not has_access:
            logger.warning(
                "User [%s] has no access to provider [%s].", user.id, provider.name
            )
        return has_access
