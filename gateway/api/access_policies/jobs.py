"""
Access policies implementation for Job access
"""
import logging
from django.contrib.auth.models import AbstractUser

from api.models import Job
from api.access_policies.providers import ProviderAccessPolicy
from api.repositories.functions import FunctionRepository


logger = logging.getLogger("gateway")


class JobAccessPolicies:
    """
    The main objective of this class is to manage the access for the user
    to the Job entities.
    """

    @staticmethod
    def can_access(user: type[AbstractUser], job: Job) -> bool:
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
    def can_read_result(user: type[AbstractUser], job: Job) -> bool:
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
    def can_save_result(user: type[AbstractUser], job: Job) -> bool:
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
    def can_update_sub_status(user: type[AbstractUser], job: Job) -> bool:
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

    @staticmethod
    def can_read_logs(user: type[AbstractUser], job: Job) -> bool:
        """
        Checks if the user has permissions to read the logs of a job.

        Access is granted if:
        - The user is the author of the job
        - The user has access to the provider and has consent to view logs for the function

        Args:
            user: Django user from the request
            job: Job instance against which to check the permission

        Returns:
            bool: True if the user has permission to read logs, False otherwise
        """
        if user.id == job.author.id:
            return True

        if not job.program.provider or not ProviderAccessPolicy.can_access(
            user, job.program.provider
        ):
            return False

        function_repository = FunctionRepository()
        consent = function_repository.get_log_consent(user, job.function)

        return consent is not None and consent.accepted
