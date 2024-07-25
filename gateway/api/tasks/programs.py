"""
This file contains the main tasks to manage programs
"""

import json
import logging
from django.conf import settings
from django.contrib.auth.models import Group, Permission

from api.models import RUN_PROGRAM_PERMISSION, Program, Provider


logger = logging.getLogger("gateway")


def assign_run_permission():
    """
    This method assigns the run permission to a group and
    assigns that group to a specific program.
    """
    try:
        functions_permissions = json.loads(settings.FUNCTIONS_PERMISSIONS)
    except json.JSONDecodeError:
        logger.error(
            "Assign run permission JSON malformed in settings.FUNCTIONS_PERMISSIONS"
        )
        return
    except Exception:  # pylint: disable=broad-exception-caught
        logger.error("Assign run permission unexpected error")
        return

    for function_title, function_info in functions_permissions.items():
        provider_name = function_info["provider"]
        instances_titles = function_info["instances"]

        program = None
        provider = Provider.objects.filter(name=provider_name).first()
        if provider is None:
            logger.warning("Provider [%s] does not exist", provider_name)
        else:
            program = Program.objects.filter(
                title=function_title, provider=provider
            ).first()

        if program is None:
            logger.warning(
                "Program [%s] does not exist for Provider [%s]",
                function_title,
                provider_name,
            )
        else:
            run_permission = Permission.objects.get(codename=RUN_PROGRAM_PERMISSION)

            groups = []
            for instance_title in instances_titles:
                group = Group.objects.filter(name=instance_title).first()
                if group is None:
                    logger.warning("Group [%s] does not exist", instance_title)
                else:
                    logger.info("Group [%s] does not exist", instance_title)
                    group.permissions.add(run_permission)
                    groups.append(group)

            logger.info(
                "Program [%s] is going to be updated with [%s] groups",
                program.title,
                len(groups),
            )
            program.instances.set(groups)
