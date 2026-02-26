"""This module contains the usecase get_jobs"""

# pylint: disable=duplicate-code
from typing import List, Tuple

from api.access_policies.providers import ProviderAccessPolicy
from api.domain.exceptions.provider_not_found_exception import ProviderNotFoundException
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from core.models import Job
from api.repositories.functions import FunctionRepository
from api.repositories.jobs import JobFilters, JobsRepository
from api.repositories.providers import ProviderRepository


class JobsProviderListUseCase:
    """Use case for retrieving provider jobs with optional filtering and pagination."""

    provider_repository = ProviderRepository()
    function_repository = FunctionRepository()
    jobs_repository = JobsRepository()

    def execute(
        self,
        user,
        filters: JobFilters,
    ) -> Tuple[List[Job], int]:
        """
        Retrieve provider jobs with access validation.

        Returns:
            tuple[list[Job], int]: (jobs, total_count)

        Raises:
            ProviderNotFoundException: If provider doesn't exist or access denied.
            FunctionNotFoundException: If function doesn't exist or access denied.
        """
        provider = self.provider_repository.get_provider_by_name(filters.provider)
        if not provider or not ProviderAccessPolicy.can_access(user, provider):
            raise ProviderNotFoundException(filters.provider)

        if filters.function:
            function = self.function_repository.get_function(
                function_title=filters.function,
                provider_name=filters.provider,
            )

            if not function:
                raise FunctionNotFoundException(function=filters.function, provider=filters.provider)

        queryset, total = self.jobs_repository.get_user_jobs(user=None, filters=filters)
        return list(queryset), total
