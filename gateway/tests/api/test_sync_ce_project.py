"""Tests for the sync_ce_project management command."""

from unittest.mock import MagicMock, patch

import pytest
import urllib3
from django.conf import settings as django_settings
from django.core.management import call_command
from django.core.management.base import CommandError

from api.management.commands import sync_ce_project
from core.models import CodeEngineProject

_MODULE = "api.management.commands.sync_ce_project"
_SEAM = f"{_MODULE}._lookup_subnet_pool_id"
_PROJECT_SEAM = f"{_MODULE}._lookup_project"


def _resolved_project(project_id="ce-1", resource_group_id="rg-1"):
    """Return a stub project as _lookup_project would.

    Defaults agree with the ids in _project(), because a name resolving to a different id
    than the one configured beside it is an error the command refuses. Tests that want a
    disagreement pass it explicitly.
    """
    project = MagicMock()
    project.id = project_id
    project.resource_group_id = resource_group_id
    return project


def _project(**overrides):
    """Build a CE_PROJECTS entry with all keys sync_ce_project requires."""
    data = {
        "project_id": "ce-1",
        "project_name": "qiskit-functions",
        "region": "us-east",
        "resource_group_id": "rg-1",
        "subnet_pool_id": "subnet-1",
        "pds_name_state": "pds-state",
        "pds_name_users": "pds-users",
        "pds_name_providers": "pds-providers",
        "cos_instance_name": "cos-instance",
        "cos_key_name": "cos-key",
        "cos_bucket_task_store_name": "task-bucket",
        "cos_bucket_user_data_name": "user-bucket",
        "cos_bucket_provider_data_name": "provider-bucket",
    }
    data.update(overrides)
    return data


def _name_only(**overrides):
    """Build a CE_PROJECTS entry that gives a subnet pool name and no id."""
    data = _project(subnet_pool_name="my-pool", **overrides)
    del data["subnet_pool_id"]
    return data


@pytest.mark.django_db
class TestSyncCeProject:
    """sync_ce_project upserts CodeEngineProject rows from settings.CE_PROJECTS."""

    @pytest.fixture(autouse=True)
    def _api_key(self, settings):
        """Give every test an API key, so none of them depend on the ambient environment.

        Any entry configuring a subnet_pool_name is refused outright when
        settings.IBM_CLOUD_API_KEY is empty, and that setting is read from the process
        environment. Without this the outcome differs between a developer machine that
        happens to export the variable and CI, which does not.
        """
        settings.IBM_CLOUD_API_KEY = "test-api-key"

    def test_creates_then_updates_in_place(self, settings):
        """A second run with a changed field updates the same row (idempotent upsert)."""
        settings.CE_PROJECTS = [_project(region="us-east")]
        call_command("sync_ce_project")

        assert CodeEngineProject.objects.count() == 1
        project = CodeEngineProject.objects.get(project_id="ce-1")
        assert project.region == "us-east"
        assert project.active is True

        settings.CE_PROJECTS = [_project(region="eu-de")]
        call_command("sync_ce_project")

        assert CodeEngineProject.objects.count() == 1
        project.refresh_from_db()
        assert project.region == "eu-de"

    def test_empty_projects_is_noop(self, settings):
        """Empty CE_PROJECTS makes no changes (never wipes existing rows)."""
        settings.CE_PROJECTS = []
        call_command("sync_ce_project")
        assert CodeEngineProject.objects.count() == 0

    def test_id_only_config_makes_no_cloud_calls(self, settings):
        """A config giving subnet_pool_id never touches the CE API.

        Load-bearing: the fleets integration test runs this command with a fake API key,
        and the CE mock is not installed for management commands.
        """
        settings.CE_PROJECTS = [_project(subnet_pool_id="subnet-1")]

        with patch(_SEAM) as lookup:
            call_command("sync_ce_project")

        lookup.assert_not_called()
        assert CodeEngineProject.objects.get(project_id="ce-1").subnet_pool_id == "subnet-1"

    def test_subnet_pool_name_is_resolved_and_stored(self, settings):
        """A name-only config stores the id the lookup returns."""
        settings.CE_PROJECTS = [_name_only()]

        with patch(_SEAM, return_value="resolved-id") as lookup:
            call_command("sync_ce_project")

        lookup.assert_called_once_with("ce-1", "us-east", "my-pool")
        assert CodeEngineProject.objects.get(project_id="ce-1").subnet_pool_id == "resolved-id"

    def test_configured_id_wins_over_a_name_without_looking_it_up(self, settings):
        """With both a name and an id configured, the id is used and nothing is called.

        This is the id-first rule: there is no point spending an IAM token and a list call
        to rediscover an id the manifest already carries.
        """
        settings.CE_PROJECTS = [_project(subnet_pool_name="my-pool", subnet_pool_id="subnet-1")]

        with patch(_SEAM) as lookup:
            call_command("sync_ce_project")

        lookup.assert_not_called()
        assert CodeEngineProject.objects.get(project_id="ce-1").subnet_pool_id == "subnet-1"

    def test_transient_network_error_is_caught_and_fails_the_entry(self, settings):
        """A timeout is not an ApiException, and must still be caught rather than escape.

        The vendored CE client only turns SSL errors and non-2xx responses into
        ApiException, so a DNS failure or timeout arrives as a raw urllib3 error. Caught, it
        is a failed entry with a readable log; uncaught, it is a traceback out of the Job.
        """
        settings.CE_PROJECTS = [_name_only()]
        timeout = urllib3.exceptions.ReadTimeoutError(None, "https://api.us-east.codeengine.cloud.ibm.com", "too slow")

        with patch(_SEAM, side_effect=timeout):
            with pytest.raises(CommandError):
                call_command("sync_ce_project")

        assert CodeEngineProject.objects.count() == 0

    def test_dry_run_checks_a_name_the_real_run_would_not_look_at(self, settings):
        """A dry run resolves a name even when the id it would produce is configured.

        A real run uses the configured id and never notices the name is wrong, which is the
        right trade for availability but proves nothing. The dry run exists to prove the
        names resolve, so its verdict is readable from the sync status alone, with no access
        to the Job's logs.
        """
        settings.CE_PROJECTS = [_project(subnet_pool_name="my-pool", subnet_pool_id="subnet-1")]

        with patch(_PROJECT_SEAM, return_value=_resolved_project()):
            with patch(_SEAM, side_effect=ValueError("no such pool")):
                with pytest.raises(CommandError):
                    call_command("sync_ce_project", "--dry-run")

        # The same config without --dry-run uses the configured id and succeeds.
        with patch(_SEAM, side_effect=ValueError("no such pool")):
            call_command("sync_ce_project")
        assert CodeEngineProject.objects.get(project_id="ce-1").subnet_pool_id == "subnet-1"

    def test_resync_picks_up_a_changed_id_for_the_same_name(self, settings):
        """A pool recreated under the same name is re-resolved, not left stale.

        Resolution triggers on the name being configured, not on a missing id, so this is
        the behaviour that makes re-running the sync the recovery for a recreated pool.
        """
        settings.CE_PROJECTS = [_name_only()]
        with patch(_SEAM, return_value="resolved-id-1"):
            call_command("sync_ce_project")

        with patch(_SEAM, return_value="resolved-id-2"):
            call_command("sync_ce_project")

        assert CodeEngineProject.objects.get(project_id="ce-1").subnet_pool_id == "resolved-id-2"

    def test_configured_project_id_and_group_are_used_without_looking_them_up(self, settings):
        """An entry carrying every id calls nothing, project listing included."""
        settings.CE_PROJECTS = [_project()]

        with patch(_PROJECT_SEAM) as lookup_project, patch(_SEAM) as lookup_pool:
            call_command("sync_ce_project")

        lookup_project.assert_not_called()
        lookup_pool.assert_not_called()
        row = CodeEngineProject.objects.get(project_id="ce-1")
        assert (row.resource_group_id, row.subnet_pool_id) == ("rg-1", "subnet-1")

    def test_project_name_resolves_both_the_id_and_the_resource_group(self, settings):
        """With neither id configured, both come from the project the name resolves to."""
        entry = _project()
        del entry["project_id"]
        del entry["resource_group_id"]
        settings.CE_PROJECTS = [entry]

        resolved = _resolved_project(project_id="resolved-ce-id", resource_group_id="resolved-rg")
        with patch(_PROJECT_SEAM, return_value=resolved) as lookup_project:
            call_command("sync_ce_project")

        assert lookup_project.call_args.args[:2] == ("us-east", "qiskit-functions")
        row = CodeEngineProject.objects.get(project_id="resolved-ce-id")
        assert row.resource_group_id == "resolved-rg"

    def test_configured_project_id_survives_a_lookup_done_for_the_resource_group(self, settings):
        """A lookup forced by a missing resource group does not override a configured id."""
        entry = _project()
        del entry["resource_group_id"]
        settings.CE_PROJECTS = [entry]

        with patch(_PROJECT_SEAM, return_value=_resolved_project(resource_group_id="resolved-rg")):
            call_command("sync_ce_project")

        row = CodeEngineProject.objects.get(project_id="ce-1")
        assert row.resource_group_id == "resolved-rg"

    def test_dry_run_fails_when_the_name_and_the_id_disagree(self, settings):
        """A name pointing at one project and an id at another is a manifest error.

        The real run uses the id and never looks, so the dry run is the only thing that can
        catch it — and it must, or "the dry run passed" would mean nothing more than "the
        name resolved to something".
        """
        settings.CE_PROJECTS = [_project()]

        with patch(_PROJECT_SEAM, return_value=_resolved_project(project_id="a-different-id")):
            with patch(_SEAM, return_value="subnet-1"):
                with pytest.raises(CommandError):
                    call_command("sync_ce_project", "--dry-run")

        assert CodeEngineProject.objects.count() == 0

    def test_dry_run_fails_when_the_resource_group_disagrees(self, settings):
        """Same check for the resource group, which is resolved from the same project."""
        settings.CE_PROJECTS = [_project()]

        with patch(_PROJECT_SEAM, return_value=_resolved_project(project_id="ce-1", resource_group_id="other-rg")):
            with patch(_SEAM, return_value="subnet-1"):
                with pytest.raises(CommandError):
                    call_command("sync_ce_project", "--dry-run")

        assert CodeEngineProject.objects.count() == 0

    def test_dry_run_passes_when_names_and_ids_agree(self, settings):
        """The matching case still succeeds, and still writes nothing."""
        settings.CE_PROJECTS = [_project(subnet_pool_name="my-pool")]

        with patch(_PROJECT_SEAM, return_value=_resolved_project(project_id="ce-1", resource_group_id="rg-1")):
            with patch(_SEAM, return_value="subnet-1"):
                call_command("sync_ce_project", "--dry-run")

        assert CodeEngineProject.objects.count() == 0

    def test_dry_run_fails_when_the_subnet_pool_name_and_id_disagree(self, settings):
        """A pool name resolving to a different id than the one beside it is refused."""
        settings.CE_PROJECTS = [_project(subnet_pool_name="my-pool", subnet_pool_id="subnet-1")]

        with patch(_PROJECT_SEAM, return_value=_resolved_project(project_id="ce-1", resource_group_id="rg-1")):
            with patch(_SEAM, return_value="a-different-subnet"):
                with pytest.raises(CommandError):
                    call_command("sync_ce_project", "--dry-run")

        assert CodeEngineProject.objects.count() == 0

    def test_project_lookup_failure_fails_the_entry(self, settings):
        """An unresolvable project name writes nothing and exits non-zero."""
        entry = _project()
        del entry["project_id"]
        del entry["resource_group_id"]
        settings.CE_PROJECTS = [entry]

        with patch(_PROJECT_SEAM, side_effect=ValueError("no such project")):
            with pytest.raises(CommandError):
                call_command("sync_ce_project")

        assert CodeEngineProject.objects.count() == 0

    def test_a_name_resolving_to_a_new_id_does_not_create_a_second_row(self, settings):
        """Two rows for one project name would make the default-project lookup ambiguous.

        project_id is the upsert key and nothing is unique, so without this guard a renamed
        or mistyped project silently adds a row and select_default() picks between them with
        .first() and no ordering.
        """
        settings.CE_PROJECTS = [_project()]
        call_command("sync_ce_project")

        entry = _project()
        del entry["project_id"]
        settings.CE_PROJECTS = [entry]
        with patch(_PROJECT_SEAM, return_value=_resolved_project(project_id="a-different-id")):
            with pytest.raises(CommandError):
                call_command("sync_ce_project")

        assert CodeEngineProject.objects.count() == 1
        assert CodeEngineProject.objects.get().project_id == "ce-1"

    def test_one_name_in_two_regions_is_refused_in_both_modes(self, settings):
        """Two entries whose names collide after resolution must fail, dry run included.

        Code Engine scopes project names per region, so the same name in two regions is two
        real projects, and neither entry needs a configured id for this to happen. The stored
        row is no help: a dry run writes nothing, so the second entry would find no trace of
        the first and the dry run would pass a manifest the real run then rejects. The result
        would be two rows sharing one project_name, which is what makes default-project
        selection ambiguous.
        """
        east = _project(project_name="shared", region="us-east")
        west = _project(project_name="shared", region="eu-de")
        for entry in (east, west):
            del entry["project_id"]
            del entry["resource_group_id"]
        settings.CE_PROJECTS = [east, west]

        by_region = {
            "us-east": _resolved_project(project_id="id-east", resource_group_id="rg-east"),
            "eu-de": _resolved_project(project_id="id-de", resource_group_id="rg-de"),
        }
        for extra_args in ([], ["--dry-run"]):
            CodeEngineProject.objects.all().delete()
            with patch(_PROJECT_SEAM, side_effect=lambda region, _n, _c: by_region[region]):
                with patch(_SEAM, return_value="subnet-1"):
                    with pytest.raises(CommandError, match="shared"):
                        call_command("sync_ce_project", *extra_args)

    def test_two_entries_resolving_to_one_id_are_refused(self, settings):
        """The mirror case: one project claimed under two names would silently overwrite."""
        settings.CE_PROJECTS = [
            _project(project_name="name-a", project_id="shared-id"),
            _project(project_name="name-b", project_id="shared-id"),
        ]

        with pytest.raises(CommandError, match="name-b"):
            call_command("sync_ce_project")

        assert CodeEngineProject.objects.count() == 1

    def test_project_listing_is_fetched_once_for_many_entries(self, settings):
        """The listing is account-wide, so entries in one region share a single call."""
        entries = []
        for name in ("one", "two", "three"):
            entry = _project(project_name=name)
            del entry["project_id"]
            del entry["resource_group_id"]
            entries.append(entry)
        settings.CE_PROJECTS = entries

        with patch(f"{_MODULE}.list_projects", return_value=[]) as listing:
            with patch(f"{_MODULE}.pick_project", side_effect=lambda _p, **kw: _resolved_project(kw["name"])):
                with patch(f"{_MODULE}.get_ce_auth"):
                    call_command("sync_ce_project")

        listing.assert_called_once()
        assert CodeEngineProject.objects.count() == 3

    def test_lookup_builds_the_client_for_the_entrys_region_and_project(self):
        """The seam itself threads region and project id into the CE client.

        Every other test here patches this function, so without this one a rename in
        get_ce_auth or FleetHandler would leave the suite green and break in production.
        """
        with (
            patch(f"{_MODULE}.get_ce_auth") as get_ce_auth,
            patch(f"{_MODULE}.FleetHandler") as fleet_handler,
        ):
            fleet_handler.return_value.resolve_subnet_pool_id.return_value = "resolved-id"
            result = sync_ce_project._lookup_subnet_pool_id(  # pylint: disable=protected-access
                "ce-1", "eu-de", "my-pool"
            )

        get_ce_auth.assert_called_once_with(django_settings.IBM_CLOUD_API_KEY, "eu-de")
        assert fleet_handler.call_args.kwargs == {
            "ce_api_client": get_ce_auth.return_value.api_client,
            "project_id": "ce-1",
        }
        fleet_handler.return_value.resolve_subnet_pool_id.assert_called_once_with("my-pool")
        assert result == "resolved-id"

    def test_lookup_failure_without_fallback_exits_nonzero(self, settings):
        """A name that will not resolve, with no id to fall back to, fails the command."""
        settings.CE_PROJECTS = [_name_only()]

        with patch(_SEAM, side_effect=ValueError("no such pool")):
            with pytest.raises(CommandError):
                call_command("sync_ce_project")

        assert CodeEngineProject.objects.count() == 0

    def test_lookup_failure_keeps_existing_row_id(self, settings):
        """A failed lookup never overwrites an id already stored on the row."""
        settings.CE_PROJECTS = [_name_only()]
        with patch(_SEAM, return_value="resolved-id"):
            call_command("sync_ce_project")

        with patch(_SEAM, side_effect=ValueError("pool went away")):
            with pytest.raises(CommandError):
                call_command("sync_ce_project")

        assert CodeEngineProject.objects.get(project_id="ce-1").subnet_pool_id == "resolved-id"

    def test_missing_api_key_with_name_config_writes_nothing(self, settings):
        """Without an API key, a name-bearing config fails before anything is written."""
        settings.CE_PROJECTS = [_name_only()]
        settings.IBM_CLOUD_API_KEY = None

        with pytest.raises(CommandError, match="IBM_CLOUD_API_KEY"):
            call_command("sync_ce_project")

        assert CodeEngineProject.objects.count() == 0

    def test_dry_run_resolves_but_writes_nothing(self, settings):
        """--dry-run reports what it would write without touching the database."""
        settings.CE_PROJECTS = [_name_only()]

        with patch(_PROJECT_SEAM, return_value=_resolved_project()):
            with patch(_SEAM, return_value="resolved-id") as lookup:
                call_command("sync_ce_project", "--dry-run")

        lookup.assert_called_once()
        assert CodeEngineProject.objects.count() == 0

    def test_one_bad_entry_does_not_block_the_others(self, settings):
        """Every entry is attempted, and the command still fails if any did not sync."""
        settings.CE_PROJECTS = [
            _name_only(project_id="ce-bad", project_name="bad-project"),
            _project(project_id="ce-good", project_name="other"),
        ]

        with patch(_SEAM, side_effect=ValueError("no such pool")):
            with pytest.raises(CommandError, match="bad-project"):
                call_command("sync_ce_project")

        assert CodeEngineProject.objects.filter(project_id="ce-good").exists()
        assert not CodeEngineProject.objects.filter(project_id="ce-bad").exists()
