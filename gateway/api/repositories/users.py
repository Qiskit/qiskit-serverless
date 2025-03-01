"""
Repository implementation for Groups model
"""

import logging
from typing import List
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.db.models import Q

from api.models import VIEW_PROGRAM_PERMISSION


User = get_user_model()
logger = logging.getLogger("gateway.repositories.user")


class UserRepository:
    """
    The main objective of this class is to manage the access to the model
    """

    def get_or_create_by_id(self, user_id: str) -> type[AbstractUser]:
        """
        This method returns a user by its id. If the user does not
        exist its created.

        Args:
            user_id: id of the user

        Returns:
            List[Group]: all the groups available to the user
        """

        user, created = User.objects.get_or_create(username=user_id)
        if created:
            logger.debug("New user created")

        return user

    def get_groups_by_permissions(self, user, permission_name: str) -> List[Group]:
        """
        Returns all the groups associated to a permission available in the user.

        Args:
            user: Django user from the request
            permission_name (str): name of the permission by look for

        Returns:
            List[Group]: all the groups available to the user
        """

        function_permission = Permission.objects.get(codename=permission_name)
        user_criteria = Q(user=user)
        permission_criteria = Q(permissions=function_permission)

        return Group.objects.filter(user_criteria & permission_criteria)

    def restart_user_groups(
        self, user: type[AbstractUser], unique_group_names: List[str]
    ) -> None:
        """
        This method will restart all the groups from a user given a specific list
        with the new groups.

        Args:
            user: Django user
            unique_group_names List[str]: list with the names of the new groups
        """

        logger.debug("Clean user groups before update them")
        user.groups.clear()

        logger.debug("Update [%s] groups", len(unique_group_names))
        view_program = Permission.objects.get(codename=VIEW_PROGRAM_PERMISSION)
        for instance in unique_group_names:
            group, created = Group.objects.get_or_create(name=instance)
            if created:
                logger.debug("New group created")
                group.permissions.add(view_program)
            group.user_set.add(user)
