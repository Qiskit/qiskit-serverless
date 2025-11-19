from typing import Optional

from django.contrib.auth.models import Group


class GroupRepository:
    def get_group_by_id(self, group_id: int) -> Optional[Group]:
        try:
            return Group.objects.get(id=group_id)
        except Group.DoesNotExist:
            return None
