"""
Access policies implementation for Provider access
"""

import logging
from typing import Optional

from core.models import (
    Provider,
    PLATFORM_PERMISSION_JOB_READ,
    PLATFORM_PERMISSION_PROVIDER_FILES,
    PLATFORM_PERMISSION_PROVIDER_JOBS,
    PLATFORM_PERMISSION_PROVIDER_LOGS,
    PLATFORM_PERMISSION_PROVIDER_UPLOAD,
)
from api.domain.authorization.function_access_result import FunctionAccessResult

logger = logging.getLogger("api.ProviderAccessPolicy")


def _check(
    user,
    provider: Provider,
    function_title: str,
    accessible_functions: Optional[FunctionAccessResult],
    permission: str,
) -> bool:
    """Core provider access logic shared by all named methods.

    When accessible_functions.has_response=True: checks the specific function entry (granular).
    Otherwise falls back to Django admin_groups.
    """
    # Runtime instances API has function granularity: user needs to have permission per function
    if accessible_functions is not None and accessible_functions.has_response:
        return accessible_functions.has_permission_for_function(provider.name, function_title, permission)
    # Legacy Django auth has provider granularity: user needs to be a provider admin
    user_groups = set(user.groups.all())
    return bool(user_groups.intersection(set(provider.admin_groups.all())))


class ProviderAccessPolicy:
    """
    The main objective of this class is to manage the access for the user
    to the Provider entities.
    """

    @staticmethod
    def can_retrieve_job(
        user,
        provider: Provider,
        function_title: str,
        accessible_functions: Optional[FunctionAccessResult] = None,
    ) -> bool:
        """Runtime instances: checks function has job.retrieve permission. Legacy: checks provider admin group."""
        if provider is None:
            raise ValueError("provider cannot be None")
        has_access = _check(user, provider, function_title, accessible_functions, PLATFORM_PERMISSION_JOB_READ)
        if not has_access:
            logger.warning("[can_retrieve_job] provider=%s user_id=%s | no access", provider.name, user.id)
        return has_access

    @staticmethod
    def can_read_logs(
        user,
        provider: Provider,
        function_title: str,
        accessible_functions: Optional[FunctionAccessResult] = None,
    ) -> bool:
        """Runtime instances: checks function has provider.logs permission. Legacy: checks provider admin group."""
        if provider is None:
            raise ValueError("provider cannot be None")
        has_access = _check(user, provider, function_title, accessible_functions, PLATFORM_PERMISSION_PROVIDER_LOGS)
        if not has_access:
            logger.warning("[can_read_logs] provider=%s user_id=%s | no access", provider.name, user.id)
        return has_access

    @staticmethod
    def can_list_jobs(
        user,
        provider: Provider,
        function_title: str,
        accessible_functions: Optional[FunctionAccessResult] = None,
    ) -> bool:
        """Runtime instances: checks function has provider.jobs permission. Legacy: checks provider admin group."""
        if provider is None:
            raise ValueError("provider cannot be None")
        has_access = _check(user, provider, function_title, accessible_functions, PLATFORM_PERMISSION_PROVIDER_JOBS)
        if not has_access:
            logger.warning("[can_list_jobs] provider=%s user_id=%s | no access", provider.name, user.id)
        return has_access

    @staticmethod
    def can_manage_files(
        user,
        provider: Provider,
        function_title: str,
        accessible_functions: Optional[FunctionAccessResult] = None,
    ) -> bool:
        """Runtime instances: checks function has provider.files permission. Legacy: checks provider admin group."""
        if provider is None:
            raise ValueError("provider cannot be None")
        has_access = _check(user, provider, function_title, accessible_functions, PLATFORM_PERMISSION_PROVIDER_FILES)
        if not has_access:
            logger.warning("[can_manage_files] provider=%s user_id=%s | no access", provider.name, user.id)
        return has_access

    @staticmethod
    def can_upload_function(
        user,
        provider: Provider,
        function_title: str,
        accessible_functions: Optional[FunctionAccessResult] = None,
    ) -> bool:
        """Runtime instances: checks function has provider.upload permission. Legacy: checks provider admin group."""
        if provider is None:
            raise ValueError("provider cannot be None")
        has_access = _check(user, provider, function_title, accessible_functions, PLATFORM_PERMISSION_PROVIDER_UPLOAD)
        if not has_access:
            logger.warning("[can_upload_function] provider=%s user_id=%s | no access", provider.name, user.id)
        return has_access

    @staticmethod
    def is_provider_admin(user, provider: Provider) -> bool:
        """True if the user belongs to any of the provider's admin groups (Django groups fallback only)."""
        if provider is None:
            raise ValueError("provider cannot be None")
        user_groups = set(user.groups.all())
        return bool(user_groups.intersection(set(provider.admin_groups.all())))
