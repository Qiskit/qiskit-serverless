"""
Access policies implementation for Provider access
"""

import logging
from typing import Optional, TYPE_CHECKING

from core.models import Provider

if TYPE_CHECKING:
    from api.domain.authorization.function_access_result import FunctionAccessResult

logger = logging.getLogger("api.ProviderAccessPolicy")


class ProviderAccessPolicy:
    """
    The main objective of this class is to manage the access for the user
    to the Provider entities.
    """

    @staticmethod
    def can_access(
        user,
        provider: Provider,
        accessible_functions: Optional["FunctionAccessResult"] = None,
        permission: Optional[str] = None,
    ) -> bool:
        """
        Checks if the user has access to a Provider.

        When accessible_functions.has_response=True, checks the external client
        result for the provider without hitting the database.
        Otherwise falls back to Django admin groups.

        Args:
            user: Django user from the request
            provider: Provider instance to check access against
            accessible_functions: Result from FunctionAccessClient; if None or
                has_response=False, falls back to Django groups
            permission: Platform permission constant (e.g. PLATFORM_PERMISSION_PROVIDER_JOBS)

        Returns:
            bool: True if the user has access
        """
        if provider is None:
            raise ValueError("provider cannot be None")

        if accessible_functions is not None and accessible_functions.has_response:
            has_access = accessible_functions.has_permission_for_provider(provider.name, permission)
            if not has_access:
                logger.warning(
                    "[can_access] provider=%s user_id=%s permission=%s | no access (external client)",
                    provider.name,
                    user.id,
                    permission,
                )
            return has_access

        # Fallback: Django groups
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
