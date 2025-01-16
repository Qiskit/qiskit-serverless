"""
Access policies implementation for Job access
"""
import logging

from api.models import Job


logger = logging.getLogger("gateway")


class JobAccessPolocies:  # pylint: disable=too-few-public-methods
    """
    The main objective of this class is to manage the access for the user
    to the Job entities.
    """

    @staticmethod
    def can_save_result(user, job: Job) -> bool:
        """
        Checks if the user has access to a Provider:

        Args:
            user: Django user from the request
            job: Job instance against to check the access

        Returns:
            bool: True or False in case the user has access
        """

        has_access = user.id == job.author
        if not has_access:
            logger.warning("User [%s] has no access to job [%s].", user.id, job.author)
        return has_access
