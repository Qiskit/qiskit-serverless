"""This module contains the usecase get_jobs"""
import logging
from typing import List, Tuple, Optional
from api.models import Job, VIEW_PROGRAM_PERMISSION
from api.access_policies.providers import ProviderAccessPolicy
from api.repositories.jobs import JobsRepository, JobFilters
from api.repositories.providers import ProviderRepository
from api.repositories.functions import FunctionRepository

logger = logging.getLogger("gateway.use_cases.get_jobs")


class ProviderNotFoundException(Exception):
    """Provider not found or access denied."""


class FunctionNotFoundException(Exception):
    """Function not found or access denied."""


class GetProviderJobsUseCase:
    """Use case for retrieving user jobs with optional filtering and pagination."""

    provider_repo = ProviderRepository()
    function_repo = FunctionRepository()
    jobs_repo = JobsRepository()

    def __init__(  # pylint:  disable=too-many-positional-arguments
        self,
        user,
        provider: str,
        function: str,
        limit: Optional[int],
        offset: Optional[int],
    ):
        self.user = user
        self.provider = provider
        self.function = function
        self.limit = limit
        self.offset = offset

    def execute(self) -> Tuple[List[Job], int]:
        """
        Retrieve provider jobs with access validation.

        Returns:
            tuple[list[Job], int]: A tuple containing:
                - List of Job objects matching the criteria (empty if no results)
                - Total count of jobs matching filters (before pagination)

        Raises:
            ProviderNotFoundException: If provider doesn't exist or user lacks access.
            FunctionNotFoundException: If function doesn't exist or user lacks permission.
        """

        # validate provider access
        provider = self.provider_repo.get_provider_by_name(self.provider)
        if not provider or not ProviderAccessPolicy.can_access(self.user, provider):
            raise ProviderNotFoundException()

        # validate function access
        function = self.function_repo.get_function_by_permission(
            user=self.user,
            permission_name=VIEW_PROGRAM_PERMISSION,
            function_title=self.function,
            provider_name=self.provider,
        )
        if not function:
            raise FunctionNotFoundException()

        filters = JobFilters(function=self.function)
        queryset, total = self.jobs_repo.get_user_jobs(
            user=self.user, filters=filters, limit=self.limit, offset=self.offset
        )
        return list(queryset), total
