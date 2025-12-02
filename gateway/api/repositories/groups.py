"""
Repository implementation for Group model
"""

from typing import Optional

from django.contrib.auth.models import Group


class GroupRepository:
    """
    Repository to manage all read and write operations on the Groups table.
    """

    def get_group_by_id(self, group_id: int) -> Optional[Group]:
        """Returns the group with the given id."""
        try:
            return Group.objects.get(id=group_id)
        except Group.DoesNotExist:
            return None
