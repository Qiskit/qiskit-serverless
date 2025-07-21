"""
Repository implementation for Job model
"""
import logging
from typing import List, Optional, Tuple
from django.db.models import Q, QuerySet
from api.models import Job
from api.models import Program as Function

logger = logging.getLogger("gateway")


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

    def _paginate_queryset(
        self, queryset: QuerySet, limit: Optional[int], offset: Optional[int]
    ) -> Tuple[List, int]:
        """Applies pagination and returns (results, total_count)."""
        if limit is not None and limit < 0:
            raise ValueError("Limit must be non-negative")
        if offset is not None and offset < 0:
            raise ValueError("Offset must be non-negative")

        total_count = queryset.count()

        if offset is not None or limit is not None:
            start = offset or 0
            end = (start + limit) if limit is not None else None

            if start >= total_count > 0:
                return [], total_count

            queryset = queryset[start:end]

        return list(queryset), total_count

    def get_user_jobs(
        self,
        user,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        ordering="-created",
    ) -> Tuple[List[Job], int]:
        """
        Retrieves jobs created by a specific user.

        Args:
            user (User): The user whose jobs are to be retrieved.
            limit (int, optional): Maximum number of jobs to return.
                If None, returns all results.
            offset (int, optional): Number of jobs to skip before returning
                results. If None, starts from beginning.
            ordering (str, optional): The field to order the results by.
                Defaults to "-created".

        Returns:
            Tuple[List[Job], int]: A tuple containing:
                - List of Job objects for the current page (empty list if offset
                  exceeds total)
                - Total count of jobs matching the criteria (before pagination)

        Raises:
            ValueError: If limit or offset are negative values.
        """
        queryset = Job.objects.filter(author=user).order_by(ordering)
        return self._paginate_queryset(queryset, limit, offset)

    def get_user_jobs_with_provider(
        self, user, limit: Optional[int], offset: Optional[int], ordering="-created"
    ) -> Tuple[List[Job], int]:
        """
        Retrieves jobs created by a specific user that have an associated provider.

        Args:
            user (User): The user whose jobs are to be retrieved.
            limit (int, optional): Maximum number of jobs to return. If None, returns all results.
            offset (int, optional): Number of jobs to skip before returning
                results. If None, starts from beginning.
            ordering (str, optional): The field to order the results by. Defaults to "-created".

        Returns:
            Tuple[List[Job], int]: A tuple containing:
                - List of Job objects for the current page
                - Total count of jobs matching the criteria (before pagination)
        """
        queryset = Job.objects.filter(
            Q(author=user) & ~Q(program__provider=None)
        ).order_by(ordering)
        return self._paginate_queryset(queryset, limit, offset)

    def get_user_jobs_without_provider(
        self, user, limit: Optional[int], offset: Optional[int], ordering="-created"
    ) -> Tuple[List[Job], int]:
        """
        Retrieves jobs created by a specific user that do not have an associated provider.

        Args:
            user (User): The user whose jobs are to be retrieved.
            limit (int, optional): Maximum number of jobs to return. If None, returns all results.
            offset (int, optional): Number of jobs to skip before returning results.
                If None, starts from beginning.
            ordering (str, optional): The field to order the results by. Defaults to "-created".

        Returns:
            Tuple[List[Job], int]: A tuple containing:
                - List of Job objects for the current page (empty list if offset exceeds total)
                - Total count of jobs matching the criteria (before pagination)

        Raises:
            ValueError: If limit or offset are negative values.
        """
        queryset = Job.objects.filter(
            Q(author=user) & Q(program__provider=None)
        ).order_by(ordering)
        return self._paginate_queryset(queryset, limit, offset)

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
