"""
Access policies implementation for Program (custom function) access.
"""

import logging
from typing import Optional

from django.contrib.auth.models import AbstractUser

from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import PLATFORM_PERMISSION_CUSTOM_CREATE

logger = logging.getLogger("api.ProgramAccessPolicies")


def _check_custom(
    accessible_functions: Optional[FunctionAccessResult],
    permission: str,
) -> bool:
    """Core custom-function access logic shared by all custom-function policy methods.

    Legacy auth: always allows (custom functions have no Django group restriction).
    Runtime instances: checks custom_function_permissions for the given permission.
    """
    if accessible_functions is None or accessible_functions.use_legacy_authorization:
        return True
    return accessible_functions.has_custom_permission(permission)


class ProgramAccessPolicies:
    """Access policies for user-owned (custom) functions — functions without a provider."""

    @staticmethod
    def can_create(
        user: AbstractUser,
        accessible_functions: Optional[FunctionAccessResult] = None,
    ) -> bool:
        """
        Check if the user can create or update a custom function.

        With legacy authorization (Django groups) this is always allowed.
        With Runtime instances, the instance must grant function-custom.create.

        Args:
            user: Django user from the request
            accessible_functions: Result from FunctionAccessClient; if None or
                use_legacy_authorization=True, falls back to allowing all

        Returns:
            bool: True if the user can create a custom function
        """
        has_access = _check_custom(accessible_functions, PLATFORM_PERMISSION_CUSTOM_CREATE)
        if not has_access:
            logger.warning(
                "[can_create] user_id=%s | no permission to create custom function",
                user.id,
            )
        return has_access
