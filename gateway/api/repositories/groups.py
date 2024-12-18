from typing import List
from django.contrib.auth.models import Group, Permission
from django.db.models import Q

from api.models import RUN_PROGRAM_PERMISSION, VIEW_PROGRAM_PERMISSION


class GroupRepository:
    def get_groups_with_view_permissions_from_user(self, user) -> List[Group]:
        view_program_permission = Permission.objects.get(
            codename=VIEW_PROGRAM_PERMISSION
        )
        user_criteria = Q(user=user)
        view_permission_criteria = Q(permissions=view_program_permission)

        return Group.objects.filter(user_criteria & view_permission_criteria)

    def get_groups_with_run_permissions_from_user(self, user) -> List[Group]:
        run_program_permission = Permission.objects.get(codename=RUN_PROGRAM_PERMISSION)
        user_criteria = Q(user=user)
        run_permission_criteria = Q(permissions=run_program_permission)

        return Group.objects.filter(user_criteria & run_permission_criteria)
