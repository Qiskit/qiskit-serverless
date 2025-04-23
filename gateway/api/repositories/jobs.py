"""
Repository implementation for Job model
"""
import logging
from typing import List, Optional
from django.db.models import Q
from api.models import Job
from api.models import Program as Function

logger = logging.getLogger("gateway")


class JobsRepository:  # pylint: disable=too-few-public-methods
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

    def get_user_jobs(self, user, ordering="-created") -> List[Job]:
        """
        Retrieves jobs created by a specific user.

        Args:
            user (User): The user whose jobs are to be retrieved.
            ordering (str, optional): The field to order the results by. Defaults to "-created".

        Returns:
            List[Jobs]: a list of Jobs
        """
        user_criteria = Q(author=user)
        return Job.objects.filter(user_criteria).order_by(ordering)

    def get_user_jobs_with_provider(self, user, ordering="-created") -> List[Job]:
        """
        Retrieves jobs created by a specific user that have an associated provider.

        Args:
            user (User): The user whose jobs are to be retrieved.
            ordering (str, optional): The field to order the results by. Defaults to "-created".

        Returns:
            List[Jobs]: a list of Jobs
        """
        user_criteria = Q(author=user)
        provider_exists_criteria = ~Q(program__provider=None)
        return Job.objects.filter(user_criteria & provider_exists_criteria).order_by(
            ordering
        )

    def get_user_jobs_without_provider(self, user, ordering="-created") -> List[Job]:
        """
        Retrieves jobs created by a specific user that do not have an associated provider.

        Args:
            user (User): The user whose jobs are to be retrieved.
            ordering (str, optional): The field to order the results by. Defaults to "-created".

        Returns:
            List[Job]: A queryset of Job objects without a provider.
        """
        user_criteria = Q(author=user)
        provider_not_exists_criteria = Q(program__provider=None)
        return Job.objects.filter(
            user_criteria & provider_not_exists_criteria
        ).order_by(ordering)

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
        if not updated:
            logger.warning(
                "Job[%s].sub_status cannot be updated because "
                "it is not in RUNNING state or id doesn't exist",
                job.id,
            )

        return updated == 1
