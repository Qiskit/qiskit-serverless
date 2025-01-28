"""
Access policies implementation for Job access
"""
import logging
from django.contrib.auth.models import User
from api.models import Job


logger = logging.getLogger("gateway")


class JobAccessPolocies:  # pylint: disable=too-few-public-methods
    """
    The main objective of this class is to manage the access for the user
    to the Job entities.
    """
    @staticmethod
    def can_access(user: User, job: Job) -> bool:
        """
        Checks if the user has access to a Provider:

        Args:
            user: Django user from the request
            job: Job instance against to check the access

        Returns:
            bool: True or False in case the user has access
        """

        is_provider_job = job.program and job.program.provider
        if is_provider_job:
            provider_groups = job.program.provider.admin_groups.all()
            author_groups = user.groups.all()
            has_access = any(
                group in provider_groups for group in author_groups)
        else:
            has_access = user.id == job.author.id

        if not has_access:
            logger.warning(
                "User [%s] has no access to job [%s].", user.username, job.author
            )
        return has_access

    @staticmethod
    def can_save_result(user: User, job: Job) -> bool:
        """
        Checks if the user has permissions to save the result of a job:

        Args:
            user: Django user from the request
            job: Job instance against to check the permission

        Returns:
            bool: True or False in case the user has permissions
        """

        has_access = user.id == job.author.id
        if not has_access:
            logger.warning(
                "User [%s] has no access to job [%s].", user.username, job.author
            )
        return has_access
