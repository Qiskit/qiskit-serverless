"""
Django management command that syncs CodeEngineProject rows from CE_PROJECTS.

CE_PROJECTS is a JSON array of project dicts delivered via deployment manifest.
Each dict must contain the keys listed in _REQUIRED_KEYS plus "project_id".

Run after migrations:

    migrate_with_lock -> sync_ce_project -> gunicorn
"""

import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from core.models import CodeEngineProject

logger = logging.getLogger("sync_ce_project")

_REQUIRED_KEYS = [
    "project_name",
    "region",
    "resource_group_id",
    "subnet_pool_id",
    "pds_name_state",
    "pds_name_users",
    "pds_name_providers",
    "cos_instance_name",
    "cos_key_name",
    "cos_bucket_task_store_name",
    "cos_bucket_user_data_name",
    "cos_bucket_provider_data_name",
]


def _upsert_project(project_id: str, data: dict) -> bool:
    """Create or update a single CodeEngineProject row.

    Args:
        project_id: The CE project UUID.
        data: Dict with project configuration fields.

    Returns:
        True if upsert succeeded, False if required fields are missing.
    """
    missing = [k for k in _REQUIRED_KEYS if not data.get(k)]
    if missing:
        logger.error("project_id=%s missing required fields: %s", project_id, ", ".join(missing))
        return False

    defaults = {k: data[k] for k in _REQUIRED_KEYS}
    defaults["active"] = True

    updated = CodeEngineProject.objects.filter(project_id=project_id).update(zone=None, **defaults)
    if updated:
        logger.info(
            "Updated %d CodeEngineProject row(s) [%s] region=[%s]", updated, data["project_name"], data["region"]
        )
    else:
        CodeEngineProject.objects.create(project_id=project_id, zone=None, **defaults)
        logger.info("Created CodeEngineProject [%s] region=[%s]", data["project_name"], data["region"])
    return True


class Command(BaseCommand):
    """Sync CodeEngineProject rows from CE_PROJECTS environment variable."""

    help = "Sync CodeEngineProject rows from CE_PROJECTS JSON array"

    def handle(self, *args, **options):
        projects = settings.CE_PROJECTS
        if not projects:
            logger.info("CE_PROJECTS not set or empty — skipping CodeEngineProject sync")
            return

        if not isinstance(projects, list):
            logger.error("CE_PROJECTS must be a JSON array")
            return

        logger.info("Syncing %d Code Engine project(s) from CE_PROJECTS", len(projects))
        for entry in projects:
            project_id = entry.get("project_id")
            if not project_id:
                logger.error("CE_PROJECTS entry missing 'project_id': %s", entry)
                continue
            _upsert_project(project_id, entry)
