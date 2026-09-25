"""This module contains the usecase get_jobs"""

# pylint: disable=duplicate-code
from typing import List, Optional, Set, Tuple

from api.access_policies.providers import ProviderAccessPolicy
from api.domain.exceptions.provider_not_found_exception import ProviderNotFoundException
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.model_managers.jobs import JobFilters
from core.models import Job, PLATFORM_PERMISSION_JOBS_READ, Provider
from core.models import Program as Function


class JobsProviderListUseCase:
    """Use case for retrieving provider jobs with optional filtering and pagination."""

    def execute(
        self,
        user,
        filters: JobFilters,
        accessible_functions: FunctionAccessResult,
    ) -> Tuple[List[Job], int]:
        """
        Retrieve provider jobs with access validation.

        Returns:
            tuple[list[Job], int]: (jobs, total_count)

        Raises:
            ProviderNotFoundException: If the provider doesn't exist or access is denied.
            FunctionNotFoundException: If the function doesn't exist.
        """
        provider = Provider.objects.get_by_name(filters.provider)
        if not provider:
            raise ProviderNotFoundException(filters.provider)

        function_titles = self._apply_access_scope(user, provider, filters, accessible_functions)
        if function_titles is not None:
            filters.functions = function_titles

        queryset, total = Job.objects.user_jobs_page(user=None, filters=filters)
        return list(queryset), total

    @staticmethod
    def _owned_function_titles(user, provider) -> Set[str]:
        """Titles of this provider's functions authored by the user.

        Ownership grants the provider operations (see ProviderAccessPolicy._check), so the
        unfiltered listing degrades to the caller's own functions instead of hiding the provider.
        """
        return set(Function.objects.filter(provider=provider, author=user).values_list("title", flat=True))

    @classmethod
    def _apply_access_scope(cls, user, provider, filters, accessible_functions) -> Optional[Set[str]]:
        """Validate access and return function titles to filter by, or None for no function-level filter."""

        if filters.function:
            # Filter by one specific function: validate if it has access to the function
            if not ProviderAccessPolicy.can_list_jobs(user, provider, filters.function, accessible_functions):
                raise ProviderNotFoundException(filters.provider)
            if not Function.objects.get_function(filters.function, filters.provider):
                raise FunctionNotFoundException(function=filters.function, provider=filters.provider)
            return None

        if accessible_functions.use_legacy_authorization:
            # Legacy Django groups: an admin sees every function, so no function-level filter.
            if ProviderAccessPolicy.is_provider_admin(user, provider):
                return None
            titles = cls._owned_function_titles(user, provider)
        else:
            # Runtime API instances, granularity per function: entitled titles plus authored ones.
            # `|` builds a new set -- accessible_functions is cached per (crn, token), never mutate it.
            provider_functions = accessible_functions.get_functions_by_provider(PLATFORM_PERMISSION_JOBS_READ)
            titles = provider_functions.get(filters.provider, set()) | cls._owned_function_titles(user, provider)

        if not titles:
            # If the user can't access to any function, we hide the provider with a not found
            raise ProviderNotFoundException(filters.provider)
        return titles
