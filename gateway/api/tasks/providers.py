"""
This file contains the main tasks to configure the providers
"""

import json
import logging
from django.conf import settings
from django.contrib.auth.models import Group

from api.models import Provider


logger = logging.getLogger("gateway")


def assign_admin_groups():
    """
    This method will assign a group to a provider.
    If the provider does not exist it will be created.
    """
    try:
        providers_configuration = json.loads(settings.PROVIDERS_CONFIGURATION)
    except json.JSONDecodeError:
        logger.error(
            "Assign admin group JSON malformed in settings.PROVIDERS_CONFIGURATION"
        )
        return
    except Exception:  # pylint: disable=broad-exception-caught
        logger.error("Assign admin group unexpected error")
        return

    for provider_name, provider_attributes in providers_configuration.items():
        groups = []
        admin_groups = provider_attributes["admin_groups"]
        registry = provider_attributes["registry"]

        for admin_group_name in admin_groups:
            group = Group.objects.filter(name=admin_group_name).first()
            if group is None:
                logger.warning("Group [%s] does not exist", admin_group_name)
            else:
                groups.append(group)

        provider, created = Provider.objects.update_or_create(
            name=provider_name,
            defaults={"registry": registry},
        )
        provider.admin_groups.set(groups)

        if created:
            logger.info(
                "Provider [%s] created for [%s] admin(s) with registry [%s]",
                provider.name,
                len(admin_groups),
                registry,
            )
        else:
            logger.info(
                "Provider [%s] updated for [%s] admin(s) with registry [%s]",
                provider.name,
                len(admin_groups),
                registry,
            )
