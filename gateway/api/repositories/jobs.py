"""
Repository implementation for Job model
"""
import logging
from typing import List
from api.models import Job
from django.db.models import Q

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
