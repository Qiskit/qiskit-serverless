"""
Repository implementation for Job model
"""

import logging
from uuid import UUID
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

from django.db.models import Q, QuerySet
from django.contrib.auth.models import AbstractUser

from core.models import Job
from core.models import Program as Function
from api.views.enums.type_filter import TypeFilter

logger = logging.getLogger("gateway")


@dataclass(slots=True)
class JobFilters:
    """
    Filters for Job queries.

    Attributes:
        function: Function title
        provider: Provider who owns the function
        limit: Number of results to return per page
        offset: Number of results to skip
        type: Type of job to filter
        status: Current job status
        created_after: Filter jobs created after this date
    """

    function: Optional[str] = None
    provider: Optional[str] = None

    limit: Optional[int] = None
    offset: Optional[int] = None
    filter: Optional[TypeFilter] = None
    status: Optional[str] = None
    created_after: Optional[datetime] = None


class JobsRepository:
    """
    The main objective of this class is to manage the access to the Job model
    """

    def get_job_by_id(self, job_id: UUID) -> Job:
        """
        Returns the job for the given id:

        Args:
            id (str): id of the job

        Returns:
            Job | None: job with the requested id
        """

        result_queryset = Job.objects.filter(id=job_id).first()

        if result_queryset is None:
            logger.info("Job [%s] was not found", job_id)

        return result_queryset

    def get_program_jobs(self, function: Function, ordering="-created") -> List[Job]:
        """
        Retrieves all program's jobs.

        Args:
            program (Program): The programs which jobs are to be retrieved.
            ordering (str, optional): The field to order the results by. Defaults to "-created".

        Returns:
            List[Jobs]: a list of Jobs
        """
        function_criteria = Q(program=function)
        return Job.objects.filter(function_criteria).order_by(ordering)

    def update_job_sub_status(self, job: Job, sub_status: Optional[str]) -> bool:
        """
        Updates the sub-status of a running job.

        Args:
            job (Job): The job to be updated
            sub_status (str, optional): The new sub-status.

        Returns:
            bool: If the status has been changed properly
        """
        if sub_status and sub_status not in Job.RUNNING_SUB_STATUSES:
            return False

        updated = Job.objects.filter(id=job.id, status=Job.RUNNING).update(
            sub_status=sub_status
        )
        if updated:
            logger.info(
                "Job [%s] of [%s] changed sub_status from [%s] to [%s]",
                job.id,
                job.author,
                job.sub_status,
                sub_status,
            )
        else:
            logger.warning(
                "Job [%s] sub_status cannot be updated because "
                "it is not in RUNNING state or id doesn't exist",
                job.id,
            )

        return updated == 1

    def get_user_jobs(
        self,
        user: AbstractUser,
        filters: JobFilters,
        ordering: str = "-created",
    ) -> Tuple[QuerySet[Job], int]:
        """
        Get user jobs with optional filters and pagination.

        Args:
            filters: Optional filters to apply
            limit: Max number of results
            offset: Number of results to skip
            ordering: Field to order by. Default: -created (newest first)

        Returns:
            (queryset, total_count): Filtered results and total count
        """
        queryset = Job.objects.order_by(ordering)

        if filters:
            queryset = self._apply_filters(queryset, filters=filters, author=user)

        return self._paginate_queryset(queryset, filters.limit, filters.offset)

    def _apply_filters(
        self,
        queryset: QuerySet,
        filters: JobFilters,
        author: Optional[AbstractUser] = None,
    ) -> QuerySet:
        """Apply filters to job queryset."""
        if author:
            queryset = queryset.filter(author=author)

        match filters.filter:
            case TypeFilter.CATALOG:
                if filters.provider:
                    queryset = queryset.filter(program__provider=filters.provider)
                else:
                    queryset = queryset.exclude(program__provider=None)
            case TypeFilter.SERVERLESS:
                queryset = queryset.filter(program__provider=None)

        if filters.status:
            queryset = queryset.filter(status=filters.status)

        if filters.created_after:
            queryset = queryset.filter(created__gte=filters.created_after)

        if filters.function:
            queryset = queryset.filter(program__title=filters.function)

        return queryset

    def _paginate_queryset(
        self, queryset: QuerySet, limit: int | None, offset: int | None
    ) -> tuple[QuerySet, int]:
        """Apply pagination to job queryset."""
        total_count = queryset.count()

        start = offset or 0
        end = start + limit if limit else None

        if start >= total_count > 0:
            return queryset.none(), total_count

        return queryset[start:end], total_count
