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
    "pds_name_state",
    "pds_name_users",
    "pds_name_providers",
    "cos_instance_name",
    "cos_key_name",
    "cos_bucket_task_store_name",
    "cos_bucket_user_data_name",
    "cos_bucket_provider_data_name",
]


def _resolve_subnet_pool_defaults(project_id: str, data: dict) -> dict | None:
    """Build the subnet-pool fields for the upsert defaults.

    Config supplies either ``subnet_pool_id`` directly, or ``subnet_pool_name``
    (with the id resolved and cached at submit time by the fleets runner). At least
    one must be present.

    When only a name is given, the cached ``subnet_pool_id`` on an existing row must
    survive re-sync — ``update_or_create`` overwrites every default on every boot, so
    a blank id in the defaults would wipe the cache each boot and force a needless
    re-resolution. The id is therefore only blanked when the configured name differs
    from the stored one (a rename that must invalidate the cache).

    Args:
        project_id: The CE project UUID.
        data: The config entry.

    Returns:
        A dict of subnet-pool fields to merge into the upsert defaults, or ``None``
        when neither id nor name is configured.
    """
    subnet_pool_id = data.get("subnet_pool_id")
    subnet_pool_name = data.get("subnet_pool_name")

    if not subnet_pool_id and not subnet_pool_name:
        logger.error("project_id=%s missing both subnet_pool_id and subnet_pool_name", project_id)
        return None

    defaults = {"subnet_pool_name": subnet_pool_name or None}

    if subnet_pool_id:
        # Explicit id in config wins and is written through.
        defaults["subnet_pool_id"] = subnet_pool_id
        return defaults

    # Name-only config: keep any cached id unless the name changed (rename → invalidate).
    existing = CodeEngineProject.objects.filter(project_id=project_id).values("subnet_pool_name").first()
    if existing is not None and existing["subnet_pool_name"] != subnet_pool_name:
        defaults["subnet_pool_id"] = None
    return defaults


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

    subnet_defaults = _resolve_subnet_pool_defaults(project_id, data)
    if subnet_defaults is None:
        return False

    defaults = {k: data[k] for k in _REQUIRED_KEYS}
    defaults.update(subnet_defaults)
    defaults["active"] = True

    _, created = CodeEngineProject.objects.update_or_create(
        project_id=project_id,
        defaults=defaults,
    )
    action = "Created" if created else "Updated"
    logger.info("%s CodeEngineProject [%s] region=[%s]", action, data["project_name"], data["region"])
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
