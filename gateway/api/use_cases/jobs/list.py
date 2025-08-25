"""This module contains the usecase get_jos"""
import logging
from typing import List

from django.contrib.auth.models import AbstractUser

from api.domain.exceptions.not_found_error import NotFoundError
from api.models import Job
from api.repositories.functions import FunctionRepository
from api.repositories.jobs import JobsRepository, JobFilters

logger = logging.getLogger("gateway.use_cases.jobs")


class JobsListUseCase:
    """Use case for retrieving user jobs with optional filtering and pagination."""

    function_repository = FunctionRepository()
    jobs_repository = JobsRepository()

    def execute(self, user: AbstractUser, filters: JobFilters) -> tuple[List[Job], int]:
        """
        Retrieve user jobs with optional filters and pagination.

        Returns:
            tuple[list[Job], int]: (jobs, total_count)
        """
        if filters.function:
            function = self.function_repository.get_function(
                function_title=filters.function,
                provider_name=filters.provider,
            )

            if not function:
                if filters.provider:
                    error_message = f"Qiskit Function {filters.provider}/{filters.function} doesn't exist."  # pylint: disable=line-too-long
                else:
                    error_message = f"Qiskit Function {filters.function} doesn't exist."
                raise NotFoundError(error_message)

        queryset, total = self.jobs_repository.get_user_jobs(user=user, filters=filters)

        return list(queryset), total
