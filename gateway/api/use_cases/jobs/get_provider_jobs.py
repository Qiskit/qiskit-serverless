"""This module contains the usecase get_jobs"""
# pylint: disable=duplicate-code
import logging
from typing import List, Tuple

from api.domain.exceptions.not_found_error import NotFoundError
from api.models import Job
from api.access_policies.providers import ProviderAccessPolicy
from api.repositories.jobs import JobsRepository, JobFilters
from api.repositories.providers import ProviderRepository
from api.repositories.functions import FunctionRepository

logger = logging.getLogger("gateway.use_cases.get_jobs")


class GetProviderJobsUseCase:
    """Use case for retrieving provider jobs with optional filtering and pagination."""

    provider_repository = ProviderRepository()
    function_repository = FunctionRepository()
    jobs_repository = JobsRepository()

    def execute(
        self,
        user,
        filters: JobFilters = None,
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
            raise NotFoundError(f"Provider {filters.provider} doesn't exist.")

        if filters.function:
            function = self.function_repository.get_function(
                function_title=filters.function,
                provider_name=filters.provider,
            )

            if not function:
                raise NotFoundError(
                    f"Qiskit Function {filters.provider}/{filters.function} doesn't exist."
                )

        queryset, total = self.jobs_repository.get_user_jobs(user=None, filters=filters)
        return list(queryset), total
