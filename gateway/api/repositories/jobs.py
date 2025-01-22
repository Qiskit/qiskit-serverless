"""
Repository implementation for Job model
"""
import logging
from api.models import Job
from django.db.models import Q

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

        id_criteria = Q(id=job_id)

        result_queryset = Job.objects.filter(id_criteria).first()

        if result_queryset is None:
            logger.warning("Job [%s] was not found", id)

        return result_queryset
