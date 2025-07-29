"""This module contains the usecase get_jos"""
import logging
from typing import List, Optional
from datetime import datetime
from api.models import Job
from api.repositories.jobs import JobsRepository, JobFilters
from api.views.enums.type_filter import TypeFilter

logger = logging.getLogger("gateway.use_cases.get_jobs")


class GetJobsUseCase:
    """Use case for retrieving user jobs with optional filtering and pagination."""

    jobs_repository = JobsRepository()

    def __init__(  # pylint:  disable=too-many-positional-arguments
        self,
        user,
        limit: Optional[int],
        offset: int = 0,
        type_filter: Optional[TypeFilter] = None,
        status: Optional[str] = None,
        created_after: Optional[datetime] = None,
        function_name: Optional[str] = None,
    ):
        self.user = user
        self.limit = limit
        self.offset = offset
        self.type_filter = type_filter
        self.status = status
        self.created_after = created_after
        self.function_name = function_name

    def execute(self) -> tuple[List[Job], int]:
        """
        Retrieve user jobs with optional filtering and pagination.

        Returns:
            tuple[list[Job], int]: A tuple containing:
                - List of Job objects matching the criteria (empty if no results)
                - Total count of jobs matching filters (before pagination)
        """
        filters = JobFilters(
            user=self.user,
            type=self.type_filter,
            status=self.status,
            created_after=self.created_after,
            function=self.function_name,
        )

        queryset, total = self.jobs_repository.get_user_jobs(
            filters=filters, limit=self.limit, offset=self.offset
        )

        return list(queryset), total
