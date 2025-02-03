"""
Repository implementation for Job model
"""
import logging
from api.models import Job
from api.views.enums.type_filter import TypeFilter
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

    def get_queryset(self, type_filter: TypeFilter, user):
        """
        Returns a filtered queryset of `Job` objects based on the `filter` query parameter.

        - If `filter=catalog`, returns jobs authored by the user with an existing provider.
        - If `filter=serverless`, returns jobs authored by the user without a provider.
        - Otherwise, returns all jobs authored by the user.

        Returns:
            QuerySet: A filtered queryset of `Job` objects ordered by creation date (descending).
        """
        if type_filter:
            if type_filter == TypeFilter.CATALOG:
                user_criteria = Q(author=user)
                provider_exists_criteria = ~Q(program__provider=None)
                return Job.objects.filter(
                    user_criteria & provider_exists_criteria
                ).order_by("-created")
            if type_filter == TypeFilter.SERVERLESS:
                user_criteria = Q(author=user)
                provider_not_exists_criteria = Q(program__provider=None)
                return Job.objects.filter(
                    user_criteria & provider_not_exists_criteria
                ).order_by("-created")
        return Job.objects.filter(author=user).order_by("-created")
