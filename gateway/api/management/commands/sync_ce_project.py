"""
Django management command that syncs CodeEngineProject rows from CE_PROJECTS.

CE_PROJECTS is a JSON array of project dicts delivered via deployment manifest.
Each dict must contain the keys listed in _REQUIRED_KEYS plus "project_id".

An entry may give ``subnet_pool_name`` instead of ``subnet_pool_id``; the name is
resolved against the Code Engine API here, so a name that does not resolve fails this
command rather than surfacing later as a failed job.

Run after migrations, from whatever runs them for the deployment (a migrations Job in the
IBM deployment; by hand or from CI otherwise):

    migrate_with_lock -> sync_ce_project
"""

import logging

import urllib3
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.ibm_cloud import get_ce_auth
from core.ibm_cloud.code_engine.ce_client.rest import ApiException
from core.ibm_cloud.code_engine.fleets.handler import FleetHandler
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

# Raised by the resolver for an unknown or ambiguous name, by IAMAuthenticator for a
# missing API key, and by the IBM Cloud client provider when a token cannot be fetched.
# urllib3 is in there because the vendored CE client only turns SSL errors and non-2xx
# responses into ApiException, so a DNS failure or a read timeout arrives raw — and those
# are exactly the cases where falling back to a configured id earns its keep.
_LOOKUP_ERRORS = (ValueError, ApiException, RuntimeError, urllib3.exceptions.HTTPError)


def _lookup_subnet_pool_id(project_id: str, region: str, name: str) -> str:
    """Resolve a subnet pool name to its id against the Code Engine API.

    Kept as a module-level function so tests patch this single seam and still exercise
    the fallback handling in :func:`_resolve_subnet_pool_id` for real.

    Args:
        project_id: The CE project UUID the pool belongs to.
        region: IBM Cloud region, which selects the CE API host.
        name: The subnet pool name to resolve.

    Returns:
        The id of the single pool carrying that name.

    Raises:
        ValueError: When no pool or more than one pool carries the name.
        ApiException: When the CE list call fails.
    """
    api_client = get_ce_auth(settings.IBM_CLOUD_API_KEY, region).api_client
    return FleetHandler(ce_api_client=api_client, project_id=project_id).resolve_subnet_pool_id(name)


def _resolve_subnet_pool_id(project_id: str, data: dict, *, allow_fallback: bool = True) -> str | None:
    """Return the subnet pool id to store for one config entry.

    Resolution triggers on ``subnet_pool_name`` being present rather than on a stored id
    being empty, so a pool deleted and recreated under the same name is picked up by
    re-running this command. A configured ``subnet_pool_id`` is the fallback when the
    lookup fails. With no name configured, nothing is called at all.

    Args:
        project_id: The CE project UUID.
        data: The config entry.
        allow_fallback: Whether a configured id may stand in for a failed lookup. False
            during a dry run, so that a name which does not resolve fails the entry even
            when a fallback exists — a dry run is there to prove resolution works, and a
            silent fallback would report success while proving nothing.

    Returns:
        The id to store, or None when it cannot be determined.
    """
    configured_id = data.get("subnet_pool_id")
    name = data.get("subnet_pool_name")

    if not name:
        return configured_id or None

    try:
        return _lookup_subnet_pool_id(project_id, data["region"], name)
    except _LOOKUP_ERRORS as ex:
        if configured_id and allow_fallback:
            logger.error(
                "project_id=%s could not resolve subnet_pool_name=[%s], falling back to "
                "configured subnet_pool_id=[%s]: %s",
                project_id,
                name,
                configured_id,
                ex,
            )
            return configured_id
        if configured_id:
            logger.error(
                "project_id=%s could not resolve subnet_pool_name=[%s]; a real run would fall "
                "back to configured subnet_pool_id=[%s], but this dry run reports it as a "
                "failure so the outcome is visible: %s",
                project_id,
                name,
                configured_id,
                ex,
            )
            return None
        logger.error(
            "project_id=%s could not resolve subnet_pool_name=[%s] and no subnet_pool_id "
            "is configured to fall back to: %s",
            project_id,
            name,
            ex,
        )
        return None


def _upsert_project(project_id: str, data: dict, *, dry_run: bool = False) -> bool:
    """Create or update a single CodeEngineProject row.

    The subnet pool is resolved before the upsert, so a failed lookup leaves an existing
    row untouched instead of overwriting a working id with a blank one.

    Args:
        project_id: The CE project UUID.
        data: Dict with project configuration fields.
        dry_run: When True, resolve and log but write nothing.

    Returns:
        True if the entry was synced, False if it could not be.
    """
    missing = [k for k in _REQUIRED_KEYS if not data.get(k)]
    if missing:
        logger.error("project_id=%s missing required fields: %s", project_id, ", ".join(missing))
        return False

    subnet_pool_id = _resolve_subnet_pool_id(project_id, data, allow_fallback=not dry_run)
    if not subnet_pool_id:
        logger.error("project_id=%s has no usable subnet pool — skipping", project_id)
        return False

    if data.get("subnet_pool_name"):
        logger.info(
            "Resolved subnet pool [%s] to id [%s] for project [%s]",
            data["subnet_pool_name"],
            subnet_pool_id,
            data["project_name"],
        )

    if dry_run:
        logger.info(
            "[dry-run] would upsert CodeEngineProject [%s] region=[%s] subnet_pool_id=[%s]",
            data["project_name"],
            data["region"],
            subnet_pool_id,
        )
        return True

    defaults = {k: data[k] for k in _REQUIRED_KEYS}
    defaults["subnet_pool_id"] = subnet_pool_id
    defaults["active"] = True

    _, created = CodeEngineProject.objects.update_or_create(
        project_id=project_id,
        defaults=defaults,
    )
    action = "Created" if created else "Updated"
    logger.info("%s CodeEngineProject [%s] region=[%s]", action, data["project_name"], data["region"])
    return True


def _require_api_key_for_names(projects: list[dict]) -> None:
    """Fail before anything is written when a name is configured but no API key is.

    Checked up front rather than caught per entry: a missing key and an unknown pool name
    both surface as ValueError, and an operator should not have to tell them apart from
    the logs.

    Args:
        projects: The CE_PROJECTS entries.

    Raises:
        CommandError: When any entry configures a name and no API key is available.
    """
    if settings.IBM_CLOUD_API_KEY:
        return
    needs_key = [e.get("project_id", "<missing project_id>") for e in projects if e.get("subnet_pool_name")]
    if needs_key:
        raise CommandError(
            f"IBM_CLOUD_API_KEY is not set, but these entries configure subnet_pool_name and need it "
            f"to resolve: {', '.join(needs_key)}. Nothing was written."
        )


class Command(BaseCommand):
    """Sync CodeEngineProject rows from CE_PROJECTS environment variable."""

    help = "Sync CodeEngineProject rows from CE_PROJECTS JSON array"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Resolve names and report what would be written, without writing anything. "
                "Stricter than a real run: a name that cannot be resolved fails even when a "
                "fallback subnet_pool_id is configured, so a clean dry run means every "
                "configured name really does resolve"
            ),
        )

    def handle(self, *args, **options):
        projects = settings.CE_PROJECTS
        if not projects:
            logger.info("CE_PROJECTS not set or empty — skipping CodeEngineProject sync")
            return

        if not isinstance(projects, list):
            raise CommandError("CE_PROJECTS must be a JSON array")

        _require_api_key_for_names(projects)

        dry_run = options["dry_run"]
        logger.info("Syncing %d Code Engine project(s) from CE_PROJECTS", len(projects))
        failed = []
        for entry in projects:
            project_id = entry.get("project_id")
            if not project_id:
                logger.error("CE_PROJECTS entry missing 'project_id': %s", entry)
                failed.append("<missing project_id>")
                continue
            if not _upsert_project(project_id, entry, dry_run=dry_run):
                failed.append(project_id)

        verb = "Would sync" if dry_run else "Synced"
        if failed:
            raise CommandError(
                f"{verb} {len(projects) - len(failed)} of {len(projects)} Code Engine project(s); "
                f"failed: {', '.join(failed)}"
            )
        logger.info("%s %d of %d Code Engine project(s)", verb, len(projects), len(projects))
