"""
Access policies implementation for Program access
"""
import logging

from django.contrib.auth.models import Group, Permission
from django.db.models import Q


from api.models import Provider


logger = logging.getLogger("gateway")


class ProviderAccessPolicy:
    @staticmethod
    def can_access(user, provider: Provider) -> bool:
        user_groups = user.groups.all()
        admin_groups = provider.admin_groups.all()
        has_access = any(group in admin_groups for group in user_groups)
        if not has_access:
            logger.warning(
                "User [%s] has no access to provider [%s].", user.id, provider.name
            )
        return has_access
