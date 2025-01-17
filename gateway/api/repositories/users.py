"""
Repository implementation for Groups model
"""

import logging
from typing import List
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db.models import Q


User = get_user_model()
logger = logging.getLogger("gateway")


class UserRepository:  # pylint: disable=too-few-public-methods
    """
    The main objective of this class is to manage the access to the model
    """

    def get_user_by_id(self, user_id: str):
        """
        Returns a user by its id

        Args:
            user_id: id of the user in database

        Returns:
            User | None: if it exists
        """

        result_queryset = User.objects.filter(id=user_id).first()

        if result_queryset is None:
            logger.warning("Function [%s] was not found", user_id)

        return result_queryset

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
