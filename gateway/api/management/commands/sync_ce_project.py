"""
Django management command that syncs CodeEngineProject rows from environment variables.

Two modes:

Single-project (existing behaviour, backward compatible):
    Set CE_PROJECT_ID plus the required CE_* vars. Optionally set CE_ZONE to pin
    the project to an availability zone.

Multi-project (for deployments with per-zone CE projects):
    Set CE_PROJECTS to a JSON array of project dicts. Each dict must contain the
    same keys as the single-project CE_* vars (project_id, project_name, region,
    resource_group_id, subnet_pool_id, pds_name_state, pds_name_users,
    pds_name_providers, cos_instance_name, cos_key_name,
    cos_bucket_user_data_name, cos_bucket_provider_data_name) plus an optional
    "zone" field.  When CE_PROJECTS is set, CE_PROJECT_ID / CE_* single-project
    vars are ignored.

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
    """Create or update CodeEngineProject rows from CE_* or CE_PROJECTS environment variables."""

    help = "Sync CodeEngineProject from CE_* or CE_PROJECTS environment variables"

    def handle(self, *args, **options):
        if settings.CE_PROJECTS:
            self._sync_multi()
        elif settings.CE_PROJECT_ID:
            self._sync_single()
        else:
            logger.info("Neither CE_PROJECTS nor CE_PROJECT_ID set — skipping CodeEngineProject sync")

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

    def _sync_single(self):
        """Sync from the individual CE_* environment variables (single-project mode)."""
        data = {
            "project_name": settings.CE_PROJECT_NAME,
            "region": settings.CE_REGION,
            "resource_group_id": settings.CE_RESOURCE_GROUP_ID,
            "subnet_pool_id": settings.CE_SUBNET_POOL_ID,
            "pds_name_state": settings.CE_PDS_NAME_STATE,
            "pds_name_users": settings.CE_PDS_NAME_USERS,
            "pds_name_providers": settings.CE_PDS_NAME_PROVIDERS,
            "cos_instance_name": settings.CE_COS_INSTANCE_NAME,
            "cos_key_name": settings.CE_COS_KEY_NAME,
            "cos_bucket_user_data_name": settings.CE_COS_BUCKET_USER_DATA_NAME,
            "cos_bucket_provider_data_name": settings.CE_COS_BUCKET_PROVIDER_DATA_NAME,
            "zone": settings.CE_ZONE,
        }
        _sync_project(settings.CE_PROJECT_ID, data)
