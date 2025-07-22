"""
Repository implementation for Job model
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple
from django.db.models import Q, QuerySet
from api.models import Job
from api.models import Program as Function
from api.views.enums.type_filter import TypeFilter

logger = logging.getLogger("gateway")


@dataclass
class JobFilters:
    """Simple, type-safe filters for Job queries."""

    type: Optional[TypeFilter] = None
    status: Optional[str] = None
    created_after: Optional[datetime] = None
    provider: Optional[str] = None
    function: Optional[str] = None


class JobsRepository:
    """
    The main objective of this class is to manage the access to the Job model
    """

    def get_job_by_id(self, job_id: str) -> Job:
        """
        Returns the job for the given id:

        Args:
            id (str): id of the job

        Returns:
            Job | None: job with the requested id
        """

        result_queryset = Job.objects.filter(id=job_id).first()

        if result_queryset is None:
            logger.info("Job [%s] was not found", id)

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

    def get_user_jobs(  # pylint:  disable=too-many-positional-arguments
        self,
        user,
        filters: Optional[JobFilters] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        ordering: str = "-created",
    ) -> Tuple[QuerySet[Job], int]:
        """
        Get user jobs with optional filters and pagination.

        Args:
            user: The user whose jobs to retrieve
            filters: Optional filters to apply
            limit: Max number of results
            offset: Number of results to skip
            ordering: Field to order by (default: newest first)

        Returns:
            (queryset, total_count): Filtered results and total count
        """
        queryset = Job.objects.filter(author=user).order_by(ordering)

        if filters:
            queryset = self._apply_filters(queryset, filters)

        return self._paginate_queryset(queryset, limit, offset)

    def _apply_filters(self, queryset: QuerySet, filters: JobFilters) -> QuerySet:
        """Apply filters to queryset in a clean, modular way."""
        if filters.type == TypeFilter.CATALOG:
            queryset = queryset.exclude(program__provider=None)
        elif filters.type == TypeFilter.SERVERLESS:
            queryset = queryset.filter(program__provider=None)

        if filters.status:
            queryset = queryset.filter(status=filters.status)

        if filters.created_after:
            queryset = queryset.filter(created__gte=filters.created_after)

        return queryset

    def _paginate_queryset(
        self, queryset: QuerySet, limit: Optional[int], offset: Optional[int]
    ) -> Tuple[QuerySet, int]:
        """Apply pagination to queryset."""
        if limit is not None and limit < 0:
            raise ValueError("Limit must be non-negative")
        if offset is not None and offset < 0:
            raise ValueError("Offset must be non-negative")

        total_count = queryset.count()

        if offset or limit:
            start = offset or 0
            end = (start + limit) if limit else None

            if start >= total_count > 0:
                return queryset.none(), total_count

            queryset = queryset[start:end]

        return queryset, total_count
