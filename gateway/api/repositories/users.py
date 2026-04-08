"""
Repository implementation for Groups model
"""

import logging
from typing import List
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser, Group, Permission

from api.domain.authentication.authentication_group import AuthenticationGroup
from core.models import GroupMetadata

User = get_user_model()
logger = logging.getLogger("api.UserRepository")


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

        user.groups.clear()

        for authentication_group in authentication_groups:
            group, created = Group.objects.get_or_create(name=authentication_group.group_name)
            if created:
                for permission in permissions:
                    group.permissions.add(permission)
            if authentication_group.account is not None:
                GroupMetadata.objects.update_or_create(group=group, defaults={"account": authentication_group.account})
            group.user_set.add(user)
            new_groups.append(group)

        return new_groups
