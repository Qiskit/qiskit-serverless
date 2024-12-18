"""
Access policies implementation for Program access
"""
import logging

from django.contrib.auth.models import Group, Permission
from django.db.models import Q


from api.models import RUN_PROGRAM_PERMISSION, VIEW_PROGRAM_PERMISSION, Program


logger = logging.getLogger("gateway")


class ProgramAccessPolicy:
    @staticmethod
    def can_view(user, user_view_groups, function: Program) -> bool:
        if function.author.id == user.id:
            return True

        instances = function.instances.all()
        has_access = any(group in instances for group in user_view_groups)
        # TODO: the message must be different if the function has a provider or not
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
        if function.author.id == user.id:
            return True

        instances = function.instances.all()
        has_access = any(group in instances for group in user_run_groups)
        # TODO: the message must be different if the function has a provider or not
        if not has_access:
            logger.warning(
                "User [%s] has no access to function [%s/%s].",
                user.id,
                function.provider.name,
                function.title,
            )
        return has_access
