"""This module contains the usecase get_jos"""

from typing import List

from django.contrib.auth.models import AbstractUser

from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from core.models import Job
from core.models import Program as Function
from api.repositories.jobs import JobFilters, JobsRepository


class JobsListUseCase:
    """Use case for retrieving user jobs with optional filtering and pagination."""

    jobs_repository = JobsRepository()

    def execute(self, user: AbstractUser, filters: JobFilters) -> tuple[List[Job], int]:
        """
        Retrieve user jobs with optional filters and pagination.

        Returns:
            tuple[list[Job], int]: (jobs, total_count)
        """
        # ensure function exists if filtered
        if filters.function:
            function = Function.objects.get_function(
                function_title=filters.function,
                provider_name=filters.provider,
            )

            if not function:
                raise FunctionNotFoundException(function=filters.function)

        queryset, total = self.jobs_repository.get_user_jobs(user=user, filters=filters)

        return list(queryset), total
