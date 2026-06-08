"""
Django management command that syncs CodeEngineProject rows from environment variables.

Set CE_PROJECTS to a JSON array of project dicts. Each dict must contain the
keys: project_id, project_name, region, resource_group_id, subnet_pool_id,
pds_name_state, pds_name_users, pds_name_providers, cos_instance_name,
cos_key_name, cos_bucket_user_data_name, cos_bucket_provider_data_name, plus
an optional "zone" field.

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


def _sync_project(project_id: str, data: dict) -> None:
    """Create or update a single CodeEngineProject row."""
    missing = [k for k in _REQUIRED_KEYS if not data.get(k)]
    if missing:
        logger.error("project_id=%s missing required fields: %s", project_id, ", ".join(missing))
        return

    defaults = {k: data[k] for k in _REQUIRED_KEYS}
    defaults["zone"] = data.get("zone") or None
    defaults["active"] = True

    _, created = CodeEngineProject.objects.update_or_create(
        project_id=project_id,
        zone=defaults["zone"],
        defaults=defaults,
    )
    action = "Created" if created else "Updated"
    logger.info(
        "%s CodeEngineProject [%s] region=[%s] zone=[%s]",
        action,
        data["project_name"],
        data["region"],
        defaults["zone"] or "any",
    )


class Command(BaseCommand):
    """Create or update CodeEngineProject rows from the CE_PROJECTS environment variable."""

    help = "Sync CodeEngineProject from the CE_PROJECTS environment variable"

    def handle(self, *args, **options):
        if settings.CE_PROJECTS:
            self._sync_multi()
        else:
            logger.info("CE_PROJECTS not set — skipping CodeEngineProject sync")

    def _sync_multi(self):
        """Sync from the CE_PROJECTS JSON array."""
        projects = settings.CE_PROJECTS
        if not isinstance(projects, list):
            logger.error("CE_PROJECTS must be a JSON array")
            return
        logger.info("Syncing %d Code Engine project(s) from CE_PROJECTS", len(projects))
        for entry in projects:
            project_id = entry.get("project_id")
            if not project_id:
                logger.error("CE_PROJECTS entry missing 'project_id': %s", entry)
                continue
            _sync_project(project_id, entry)
