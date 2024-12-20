"""
Repository implementation for Groups model
"""

from typing import List
from django.contrib.auth.models import Group, Permission
from django.db.models import Q


class GroupRepository:  # pylint: disable=too-few-public-methods
    """
    The main objective of this class is to manage the access to the model
    """

    def get_groups_by_permissions(self, user, permission_name: str) -> List[Group]:
        """
        Returns all the groups associated to a permission available in the user.

        Args:
            user: Django user from the request
            permission

        Returns:
            List[Group]: all the groups available to the user
        """

        function_permission = Permission.objects.get(codename=permission_name)
        user_criteria = Q(user=user)
        permission_criteria = Q(permissions=function_permission)

        return Group.objects.filter(user_criteria & permission_criteria)
