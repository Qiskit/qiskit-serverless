"""
Repository implementation for Groups model
"""

import logging
from typing import List
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.db.models import Q

from api.domain.authentication.authentication_group import AuthenticationGroup
from core.models import GroupMetadata

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
            logger.debug("New user [%s] created", user_id)

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
        self,
        user: type[AbstractUser],
        authentication_groups: List[AuthenticationGroup],
        permission_names: List[str],
    ) -> List[Group]:
        """
        This method will restart all the groups from a user given a specific list
        with the new groups.

        Args:
            user: Django user
            authentication_groups List[AuthenticationGroup]:
            list with the names and accounts of new groups
            permission_names: name of the permissions that will be applied to the new groups
        """

        new_groups = []

        permissions = []
        for permission_name in permission_names:
            permissions.append(Permission.objects.get(codename=permission_name))

        logger.debug("Clean user groups before update them")
        user.groups.clear()

        logger.debug("Update [%s] groups", len(authentication_groups))
        for authentication_group in authentication_groups:
            group, created = Group.objects.get_or_create(name=authentication_group.group_name)
            if created:
                for permission in permissions:
                    group.permissions.add(permission)
                if authentication_group.account is not None:
                    GroupMetadata.objects.create(group=group, account=authentication_group.account)
            group.user_set.add(user)
            new_groups.append(group)

        return new_groups
