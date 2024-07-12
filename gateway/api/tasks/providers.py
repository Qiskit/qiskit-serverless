"""
This file contains the main tasks to configure the providers
"""

import json
import logging
from django.conf import settings
from django.contrib.auth.models import Group

from api.models import Provider


logger = logging.getLogger("gateway")


def assign_admin_group():
    """
    This method will assign a group to a provider.
    If the provider does not exist it will be created.
    """
    try:
        providers_configuration = json.loads(settings.PROVIDERS_CONFIGURATION)
    except json.JSONDecodeError as e:
        logger.error("Assign admin group JSON malformed: %s", e)
        return
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Assign admin group unexpected error: %s", e)
        return

    for provider_name, admin_group_name in providers_configuration.items():
        group = Group.objects.filter(name=admin_group_name).first()
        if group is None:
            logger.warning("Group [%s] does not exist", admin_group_name)
        else:
            provider, created = Provider.objects.update_or_create(
                name=provider_name, defaults={"admin_group": group}
            )

            if created:
                logger.info(
                    "Provider [%s] created for admin [%s]",
                    provider.name,
                    admin_group_name,
                )
