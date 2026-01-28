"""
Access policies implementation for Job access
"""

import logging
from django.contrib.auth.models import AbstractUser

from api.models import Job
from api.access_policies.providers import ProviderAccessPolicy

logger = logging.getLogger("gateway")


class JobAccessPolicies:
    """
    The main objective of this class is to manage the access for the user
    to the Job entities.
    """

    @staticmethod
    def can_access(user: AbstractUser, job: Job) -> bool:
        """
        Checks if the user has access to the Job. As an author
        you always have access. If you are not the author you
        need to be an admin of the provider.

        Args:
            user: Django user from the request
            job: Job instance against to check the access

        Returns:
            bool: True or False in case the user has access
        """

        if user is None:
            raise ValueError("user cannot be None")

        if job is None:
            raise ValueError("job cannot be None")

        if user.id == job.author.id:
            return True

        has_access = False
        is_provider_job = job.program and job.program.provider
        if is_provider_job:
            has_access = ProviderAccessPolicy.can_access(user, job.program.provider)

        if not has_access:
            logger.warning(
                "User [%s] has no access to job [%s].", user.username, job.author
            )
        return has_access

    @staticmethod
    def can_read_result(user: AbstractUser, job: Job) -> bool:
        """
        Checks if the user has permissions to read the result of a job:

        Args:
            user: Django user from the request
            job: Job instance against to check the permission

        Returns:
            bool: True or False in case the user has permissions
        """

        has_access = user.id == job.author.id
        if not has_access:
            logger.warning(
                "User [%s] has no access to read the result of the job [%s].",
                user.username,
                job.author,
            )
        return has_access

    @staticmethod
    def can_read_logs(user: AbstractUser, job: Job) -> bool:
        """
        Checks if the user has permissions to read the result of a job:

        Args:
            user: Django user from the request
            job: Job instance against to check the permission

        Returns:
            bool: True or False in case the user has permissions
        """

        if user.id == job.author.id:
            return True

        has_access = False
        if job.program and job.program.provider:
            has_access = ProviderAccessPolicy.can_access(user, job.program.provider)
        if not has_access:
            logger.warning(
                "User [%s] has no access to read the result of the job [%s].",
                user.username,
                job.author,
            )
        return has_access

    @staticmethod
    def can_save_result(user: AbstractUser, job: Job) -> bool:
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
                "User [%s] has no access to save the result of the job [%s].",
                user.username,
                job.author,
            )
        return has_access

    @staticmethod
    def can_update_sub_status(user: AbstractUser, job: Job) -> bool:
        """
        Checks if the user has permissions to update the substatus of a job:

        Args:
            user: Django user from the request
            job: Job instance against to check the permission

        Returns:
            bool: True or False in case the user has permissions
        """

        has_access = user.id == job.author.id
        if not has_access:
            logger.warning(
                "User [%s] has no access to update the sub_status of the job [%s].",
                user.username,
                job.id,
            )
        return has_access
