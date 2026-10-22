"""
Django management command that syncs CodeEngineProject rows from CE_PROJECTS.

CE_PROJECTS is a JSON array of project dicts delivered via deployment manifest.
Each dict must contain the keys listed in _REQUIRED_KEYS.

Three ids may be left out and resolved from names instead: ``project_id`` and
``resource_group_id`` come from the project named by ``project_name``, and
``subnet_pool_id`` from ``subnet_pool_name``. A configured id is used as-is and costs no
call to IBM Cloud, so a manifest of ids syncs without touching IBM Cloud at all. A name is
looked up when the id it would produce is absent, and when a lookup happens anyway for the
other field, a configured id that disagrees with the resolved one fails the entry rather
than winning. A name that cannot be resolved fails this command rather than surfacing later
as a failed job.

Run after migrations, from whatever runs them for the deployment (a migrations Job in the
IBM deployment; by hand or from CI otherwise):

    migrate_with_lock -> sync_ce_project
"""

import logging

import urllib3
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.ibm_cloud import get_ce_auth
from core.ibm_cloud.code_engine.ce_client.models.v2_project import V2Project
from core.ibm_cloud.code_engine.ce_client.rest import ApiException
from core.ibm_cloud.code_engine.fleets.handler import FleetHandler
from core.ibm_cloud.code_engine.projects import list_projects, pick_project
from core.models import CodeEngineProject

logger = logging.getLogger("sync_ce_project")

_REQUIRED_KEYS = [
    "project_name",
    "region",
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
# responses into ApiException, so a DNS failure or a read timeout arrives raw. Caught, it is
# a failed entry with a readable log; uncaught, it is a traceback out of the command.
_LOOKUP_ERRORS = (ValueError, ApiException, RuntimeError, urllib3.exceptions.HTTPError)


def _lookup_subnet_pool_id(project_id: str, region: str, name: str) -> str:
    """Resolve a subnet pool name to its id against the Code Engine API.

    Kept as a module-level function so tests patch this single seam and still exercise the
    precedence and mismatch handling in :func:`_resolve_subnet_pool_id` for real.

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


def _lookup_project(region: str, name: str, projects_by_region: dict[str, list[V2Project]]) -> V2Project:
    """Resolve a Code Engine project name to the project it names.

    The listing is fetched at most once per region and reused, so a manifest of many entries
    costs one IAM token fetch and one listing per region rather than one of each per entry.
    Keyed by region because the *client* is region-scoped, not because the data is: the
    listing itself is account-wide.

    Kept as a module-level function so tests patch this single seam.

    Args:
        region: IBM Cloud region the project must be in.
        name: The project name to resolve.
        projects_by_region: Per-run cache of listings, keyed by region.

    Returns:
        The matching ``V2Project``.

    Raises:
        ValueError: When the name matches no single active project in that region, or when
            the API key is missing.
        ApiException: When a CE list call fails.
        RuntimeError: When an IAM token cannot be fetched.
        urllib3.exceptions.HTTPError: On a transport failure such as DNS or a timeout, which
            the vendored client does not wrap.
    """
    if region not in projects_by_region:
        api_client = get_ce_auth(settings.IBM_CLOUD_API_KEY, region).api_client
        projects_by_region[region] = list_projects(api_client)
    return pick_project(projects_by_region[region], name=name, region=region)


def _resolve_project_fields(
    data: dict, projects_by_region: dict[str, list[V2Project]], *, verify_names: bool = False
) -> tuple[str, str] | None:
    """Return the ``(project_id, resource_group_id)`` to store for one config entry.

    A configured id is used as-is and costs no call. The project is looked up only when one
    of the two ids is missing, or when ``verify_names`` asks for the name to be checked
    anyway. Note that once a lookup has happened, a configured id that disagrees with the
    resolved one fails the entry: it does not win over what the name actually resolves to.

    Args:
        data: The config entry.
        projects_by_region: Per-run cache of project listings, keyed by region.
        verify_names: Resolve the name even when both ids are configured. True during a dry
            run, whose job is to prove the names resolve.

    Returns:
        A ``(project_id, resource_group_id)`` pair, or None when it cannot be determined.
    """
    configured_id = data.get("project_id")
    configured_group = data.get("resource_group_id")
    name = data["project_name"]

    if configured_id and configured_group and not verify_names:
        return configured_id, configured_group

    try:
        project = _lookup_project(data["region"], name, projects_by_region)
    except _LOOKUP_ERRORS as ex:
        logger.error("project_name=[%s] could not be resolved: %s", name, ex)
        return None

    if not project.id or not project.resource_group_id:
        logger.error(
            "project_name=[%s] resolved to a project missing an id or resource group "
            "(id=[%s] resource_group_id=[%s])",
            name,
            project.id,
            project.resource_group_id,
        )
        return None

    # A configured id and a resolved one that disagree mean the manifest names one project
    # and points at another. Whichever is wrong, seeding either would be a guess, and a dry
    # run that let this pass would report success while proving nothing.
    if configured_id and project.id != configured_id:
        logger.error(
            "project_name=[%s] resolves to project_id=[%s], but project_id=[%s] is configured. "
            "One of the two is wrong; fix the manifest.",
            name,
            project.id,
            configured_id,
        )
        return None
    if configured_group and project.resource_group_id != configured_group:
        logger.error(
            "project [%s] is in resource_group_id=[%s], but resource_group_id=[%s] is configured. "
            "One of the two is wrong; fix the manifest.",
            name,
            project.resource_group_id,
            configured_group,
        )
        return None

    logger.info(
        "Resolved project [%s] to id [%s] resource_group_id [%s]",
        name,
        project.id,
        project.resource_group_id,
    )
    return project.id, project.resource_group_id


def _resolve_subnet_pool_id(project_id: str, data: dict, *, verify_names: bool = False) -> str | None:
    """Return the subnet pool id to store for one config entry.

    A configured ``subnet_pool_id`` wins and costs no call. The name is looked up only when
    the id is absent, or when ``verify_names`` asks for it to be checked anyway. A pool
    deleted and recreated under the same name is therefore picked up by re-running this
    command, as long as the manifest carries the name rather than the old id.

    Args:
        project_id: The CE project UUID the pool belongs to.
        data: The config entry.
        verify_names: Resolve the name even when the id is configured. True during a dry
            run, so a name that does not resolve fails even though a real run would have
            used the configured id and never noticed.

    Returns:
        The id to store, or None when it cannot be determined.
    """
    configured_id = data.get("subnet_pool_id")
    name = data.get("subnet_pool_name")

    if configured_id and not verify_names:
        return configured_id

    if not name:
        return configured_id or None

    try:
        resolved = _lookup_subnet_pool_id(project_id, data["region"], name)
    except _LOOKUP_ERRORS as ex:
        if configured_id:
            logger.error(
                "project_id=%s could not resolve subnet_pool_name=[%s]; a real run would have used "
                "the configured subnet_pool_id=[%s] without looking, but this dry run reports it as "
                "a failure so the outcome is visible: %s",
                project_id,
                name,
                configured_id,
                ex,
            )
            return None
        logger.error(
            "project_id=%s could not resolve subnet_pool_name=[%s] and no subnet_pool_id is configured: %s",
            project_id,
            name,
            ex,
        )
        return None

    if configured_id and resolved != configured_id:
        logger.error(
            "subnet_pool_name=[%s] resolves to subnet_pool_id=[%s], but subnet_pool_id=[%s] is "
            "configured. One of the two is wrong; fix the manifest.",
            name,
            resolved,
            configured_id,
        )
        return None

    logger.info("Resolved subnet pool [%s] to id [%s]", name, resolved)
    return resolved


def _conflicts_within_this_run(project_id: str, project_name: str, claimed: dict[str, str]) -> bool:
    """Whether an earlier entry in this same manifest already claimed this name or id.

    Checked separately from the stored rows because a dry run writes nothing, so without
    this the second of two clashing entries would see no trace of the first and the dry run
    would pass a manifest the real run then rejects. A copy-pasted entry with one field
    edited is exactly how that happens.

    Args:
        project_id: The resolved CE project UUID.
        project_name: The configured project name.
        claimed: Project name to resolved id, for the entries handled so far in this run.

    Returns:
        True when this entry clashes with an earlier one.
    """
    previous_id = claimed.get(project_name)
    if previous_id is not None and previous_id != project_id:
        logger.error(
            "two entries in CE_PROJECTS name project [%s] but resolve to different ids ([%s] and [%s]). "
            "Only one of them can be right.",
            project_name,
            previous_id,
            project_id,
        )
        return True

    # Linear scan rather than a reverse index: a manifest is tens of entries at most.
    for earlier_name, earlier_id in claimed.items():
        if earlier_id == project_id and earlier_name != project_name:
            logger.error(
                "two entries in CE_PROJECTS resolve to the same project_id [%s] under different names "
                "([%s] and [%s]). The second would overwrite the first.",
                project_id,
                earlier_name,
                project_name,
            )
            return True
    return False


def _conflicts_with_a_stored_row(project_id: str, project_name: str) -> bool:
    """Whether a row already stored under this project name holds a different id.

    ``project_id`` is the upsert key and the model has no unique constraint on either
    field, so a renamed or mistyped name resolving to a different id would add a *second*
    row rather than update the first. This refuses any same-name row, including an inactive
    or provider-dedicated one that ``select_default()`` would skip: this command never
    deletes rows, so two rows for one project name is confusing however they are filtered,
    and for the plain active case it is worse than confusing — ``select_default()`` picks
    between them with ``.first()`` and no ordering, sending new uploads to an arbitrary
    project.

    Args:
        project_id: The resolved CE project UUID.
        project_name: The configured project name.

    Returns:
        True when a different row already holds this project name.
    """
    clash = (
        CodeEngineProject.objects.filter(project_name=project_name)
        .exclude(project_id=project_id)
        .values_list("project_id", flat=True)
    )
    existing = list(clash)
    if existing:
        logger.error(
            "project_name=[%s] resolved to project_id=[%s], but rows already exist for that name with "
            "project_id=%s. Refusing to add a second row for one project name. Fix the name, or remove "
            "the stale row.",
            project_name,
            project_id,
            existing,
        )
        return True
    return False


def _resolve_entry(
    data: dict,
    projects_by_region: dict[str, list[V2Project]],
    claimed: dict[str, str],
    *,
    verify_names: bool = False,
) -> tuple[str, str, str] | None:
    """Work out the three ids to store for one config entry, and refuse a bad one.

    Separate from the write so that every way an entry can be rejected happens before
    anything touches the database: a failed lookup then leaves an existing row alone rather
    than overwriting a working value with a blank one.

    Args:
        data: The config entry.
        projects_by_region: Per-run cache of project listings, keyed by region.
        claimed: Project name to resolved id for entries handled earlier in this run.
        verify_names: Resolve names even where the id is configured. True during a dry run.

    Returns:
        ``(project_id, resource_group_id, subnet_pool_id)``, or None when the entry cannot
        be synced. Every None path logs why.
    """
    missing = [k for k in _REQUIRED_KEYS if not data.get(k)]
    if missing:
        logger.error("project_name=[%s] missing required fields: %s", data.get("project_name"), ", ".join(missing))
        return None

    resolved = _resolve_project_fields(data, projects_by_region, verify_names=verify_names)
    if not resolved:
        return None
    project_id, resource_group_id = resolved

    subnet_pool_id = _resolve_subnet_pool_id(project_id, data, verify_names=verify_names)
    if not subnet_pool_id:
        logger.error("project_id=%s has no usable subnet pool", project_id)
        return None

    if _conflicts_within_this_run(project_id, data["project_name"], claimed):
        return None
    if _conflicts_with_a_stored_row(project_id, data["project_name"]):
        return None

    return project_id, resource_group_id, subnet_pool_id


def _upsert_project(
    data: dict,
    projects_by_region: dict[str, list[V2Project]],
    claimed: dict[str, str],
    *,
    dry_run: bool = False,
) -> bool:
    """Create or update a single CodeEngineProject row.

    Args:
        data: Dict with project configuration fields.
        projects_by_region: Per-run cache of project listings, keyed by region.
        claimed: Project name to resolved id for entries handled earlier in this run;
            updated in place, so a clash between two entries is caught in a dry run too.
        dry_run: When True, resolve and log but write nothing.

    Returns:
        True if the entry was synced, False if it could not be.
    """
    resolved = _resolve_entry(data, projects_by_region, claimed, verify_names=dry_run)
    if not resolved:
        return False
    project_id, resource_group_id, subnet_pool_id = resolved
    claimed[data["project_name"]] = project_id

    if dry_run:
        logger.info(
            "[dry-run] would upsert CodeEngineProject [%s] region=[%s] project_id=[%s] "
            "resource_group_id=[%s] subnet_pool_id=[%s]",
            data["project_name"],
            data["region"],
            project_id,
            resource_group_id,
            subnet_pool_id,
        )
        return True

    defaults = {k: data[k] for k in _REQUIRED_KEYS}
    defaults["resource_group_id"] = resource_group_id
    defaults["subnet_pool_id"] = subnet_pool_id
    defaults["active"] = True

    _, created = CodeEngineProject.objects.update_or_create(
        project_id=project_id,
        defaults=defaults,
    )
    action = "Created" if created else "Updated"
    logger.info("%s CodeEngineProject [%s] region=[%s]", action, data["project_name"], data["region"])
    return True


def _needs_lookup(entry: dict, *, dry_run: bool) -> bool:
    """Whether this entry requires a call to IBM Cloud.

    An entry carrying every id needs nothing. A dry run resolves names whether or not the
    ids are there, since proving the names resolve is the point of it.

    Args:
        entry: The config entry.
        dry_run: Whether this is a dry run.

    Returns:
        True when the entry cannot be synced from config alone.
    """
    if dry_run:
        return bool(entry.get("project_name") or entry.get("subnet_pool_name"))
    if not entry.get("project_id") or not entry.get("resource_group_id"):
        return True
    return bool(entry.get("subnet_pool_name")) and not entry.get("subnet_pool_id")


def _require_api_key_for_lookups(projects: list[dict], *, dry_run: bool) -> None:
    """Fail before anything is written when a lookup is needed but no API key is set.

    Checked up front rather than caught per entry: a missing key and an unknown name both
    surface as ValueError, and an operator should not have to tell them apart from the logs.

    Args:
        projects: The CE_PROJECTS entries.
        dry_run: Whether this is a dry run.

    Raises:
        CommandError: When any entry needs a lookup and no API key is available.
    """
    if settings.IBM_CLOUD_API_KEY:
        return
    needs_key = [e.get("project_name") or "<unnamed entry>" for e in projects if _needs_lookup(e, dry_run=dry_run)]
    if needs_key:
        raise CommandError(
            f"IBM_CLOUD_API_KEY is not set, but these entries need it to resolve a name to an id: "
            f"{', '.join(needs_key)}. Nothing was written."
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
                "Stricter than a real run: every configured name is resolved even when the id it "
                "would produce is already configured, and a name that does not resolve, or that "
                "resolves to a different id than the one configured beside it, fails. So a clean "
                "dry run means every name in the manifest really does resolve, to the id it is "
                "paired with. Because it always resolves, a dry run always needs IBM_CLOUD_API_KEY, "
                "even for a manifest that a real run could sync from ids alone"
            ),
        )

    def handle(self, *args, **options):
        projects = settings.CE_PROJECTS
        if not projects:
            logger.info("CE_PROJECTS not set or empty — skipping CodeEngineProject sync")
            return

        if not isinstance(projects, list):
            raise CommandError("CE_PROJECTS must be a JSON array")

        dry_run = options["dry_run"]
        _require_api_key_for_lookups(projects, dry_run=dry_run)
        logger.info("Syncing %d Code Engine project(s) from CE_PROJECTS", len(projects))
        failed = []
        projects_by_region: dict[str, list[V2Project]] = {}
        claimed: dict[str, str] = {}
        for entry in projects:
            if not _upsert_project(entry, projects_by_region, claimed, dry_run=dry_run):
                failed.append(entry.get("project_name") or entry.get("project_id") or "<unnamed entry>")

        verb = "Would sync" if dry_run else "Synced"
        if failed:
            raise CommandError(
                f"{verb} {len(projects) - len(failed)} of {len(projects)} Code Engine project(s); "
                f"failed: {', '.join(failed)}"
            )
        logger.info("%s %d of %d Code Engine project(s)", verb, len(projects), len(projects))
