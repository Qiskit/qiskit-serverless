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
    except json.JSONDecodeError:
        logger.error(
            "Assign admin group JSON malformed in settings.PROVIDERS_CONFIGURATION"
        )
        return
    except Exception:  # pylint: disable=broad-exception-caught
        logger.error("Assign admin group unexpected error")
        return

    for provider_name, provider_attributes in providers_configuration.items():
        admin_group_name = provider_attributes["admin_group"]
        registry = provider_attributes["registry"]
        group = Group.objects.filter(name=admin_group_name).first()
        if group is None:
            logger.warning("Group [%s] does not exist", admin_group_name)
        else:
            provider, created = Provider.objects.update_or_create(
                name=provider_name,
                defaults={"admin_group": group, "registry": registry},
            )

            if created:
                logger.info(  #  pylint: disable=logging-too-many-args
                    "Provider [%s] created for admin [%s]",
                    provider.name,
                    admin_group_name,
                    registry,
                )
