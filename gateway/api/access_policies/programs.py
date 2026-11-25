"""
Access policies implementation for Program (Qiskit Function) access.
"""

import logging
from typing import Optional

from django.contrib.auth.models import AbstractUser

from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import (
    PLATFORM_PERMISSION_CUSTOM_WRITE,
    PLATFORM_PERMISSION_READ,
    PLATFORM_PERMISSION_RUN,
    PLATFORM_PERMISSION_USER_FILES_READ,
    PLATFORM_PERMISSION_USER_FILES_WRITE,
    RUN_PROGRAM_PERMISSION,
    VIEW_PROGRAM_PERMISSION,
    Program as Function,
)

logger = logging.getLogger("api.ProgramAccessPolicies")


def _check(user, function: Function, accessible_functions, permission: str, legacy_permission_name: str) -> bool:
    """Check a loaded provider function. Instances: the function's own entry must carry `permission`
    and authorship grants nothing. Legacy: the author, or a group of the function with the Django permission.

    Only provider functions: a custom function has no provider, so the instances path would fail on it."""
    if accessible_functions is None or accessible_functions.use_legacy_authorization:
        has_access = (
            function.author_id == user.id
            or function.instances.filter(user=user, permissions__codename=legacy_permission_name).exists()
        )
    else:
        has_access = accessible_functions.has_permission_for_function(
            function.provider.name, function.title, permission
        )
    if not has_access:
        logger.warning("[%s] function=%s user_id=%s | no access", permission, function.title, user.id)
    return has_access


class ProgramAccessPolicies:
    """Access policies for Qiskit Functions.

    Every check except `can_create` takes a provider function. A custom function is looked up by author and
    never reaches them."""

    @staticmethod
    def can_read(user, function: Function, accessible_functions: Optional[FunctionAccessResult]) -> bool:
        """Check if the user can see a provider function."""
        return _check(user, function, accessible_functions, PLATFORM_PERMISSION_READ, VIEW_PROGRAM_PERMISSION)

    @staticmethod
    def can_run(user, function: Function, accessible_functions: Optional[FunctionAccessResult]) -> bool:
        """Check if the user can run a provider function."""
        return _check(user, function, accessible_functions, PLATFORM_PERMISSION_RUN, RUN_PROGRAM_PERMISSION)

    @staticmethod
    def can_read_user_files(user, function: Function, accessible_functions: Optional[FunctionAccessResult]) -> bool:
        """Check if the user can list and download their files of a provider function."""
        return _check(user, function, accessible_functions, PLATFORM_PERMISSION_USER_FILES_READ, RUN_PROGRAM_PERMISSION)

    @staticmethod
    def can_write_user_files(user, function: Function, accessible_functions: Optional[FunctionAccessResult]) -> bool:
        """Check if the user can upload and delete their files of a provider function."""
        return _check(
            user, function, accessible_functions, PLATFORM_PERMISSION_USER_FILES_WRITE, RUN_PROGRAM_PERMISSION
        )

    @staticmethod
    def can_create(
        user: AbstractUser,
        accessible_functions: Optional[FunctionAccessResult] = None,
    ) -> bool:
        """
        Check if the user can create or update a custom function.

        With legacy authorization (Django groups) this is always allowed.
        With Runtime instances, the instance must grant function-custom.write.

        Args:
            user: Django user from the request
            accessible_functions: Result from FunctionAccessClient; if None or
                use_legacy_authorization=True, falls back to allowing all

        Returns:
            bool: True if the user can create a custom function
        """
        if accessible_functions is None or accessible_functions.use_legacy_authorization:
            return True
        has_access = accessible_functions.has_custom_permission(PLATFORM_PERMISSION_CUSTOM_WRITE)
        if not has_access:
            logger.warning(
                "[can_create] user_id=%s | no permission to create custom function",
                user.id,
            )
        return has_access
