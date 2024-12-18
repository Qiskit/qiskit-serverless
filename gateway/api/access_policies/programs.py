"""
Access policies implementation for Program access
"""
import logging

from api.models import Program


logger = logging.getLogger("gateway")


class ProgramAccessPolicy:
    """
    The main objective of this class is to manage the access for the user
    to the Program entities.
    """

    @staticmethod
    def can_view(user, user_view_groups, function: Program) -> bool:
        """
        Checks if the user has view access to a Function:
            - If it's the author it will always have access
            - a view group is in the Program.instances

        Args:
            user: Django user from the request
            user_view_groups: view groups from a user
            function: Program instance against to check the access

        Returns:
            bool: True or False in case the user has access
        """

        if function.author.id == user.id:
            return True

        instances = function.instances.all()
        has_access = any(group in instances for group in user_view_groups)
        # the message must be different if the function has a provider or not
        if not has_access:
            logger.warning(
                "User [%s] has no access to function [%s/%s].",
                user.id,
                function.provider.name,
                function.title,
            )
        return has_access

    @staticmethod
    def can_run(user, user_run_groups, function: Program) -> bool:
        """
        Checks if the user has run access to a Function:
            - If it's the author it will always have access
            - a run group is in the Program.instances

        Args:
            user: Django user from the request
            user_run_groups: run groups from a user
            function: Program instance against to check the access

        Returns:
            bool: True or False in case the user has access
        """

        if function.author.id == user.id:
            return True

        instances = function.instances.all()
        has_access = any(group in instances for group in user_run_groups)
        # the message must be different if the function has a provider or not
        if not has_access:
            logger.warning(
                "User [%s] has no access to function [%s/%s].",
                user.id,
                function.provider.name,
                function.title,
            )
        return has_access
