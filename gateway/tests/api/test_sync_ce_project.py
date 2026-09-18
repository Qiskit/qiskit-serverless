"""Tests for the sync_ce_project management command."""

from unittest.mock import patch

import pytest
import urllib3
from django.conf import settings as django_settings
from django.core.management import call_command
from django.core.management.base import CommandError

from api.management.commands import sync_ce_project
from core.models import CodeEngineProject

_MODULE = "api.management.commands.sync_ce_project"
_SEAM = f"{_MODULE}._lookup_subnet_pool_id"


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

    def test_lookup_failure_falls_back_to_configured_id(self, settings):
        """With both a name and an id configured, a failed lookup uses the id."""
        settings.CE_PROJECTS = [_project(subnet_pool_name="my-pool", subnet_pool_id="subnet-1")]

        with patch(_SEAM, side_effect=ValueError("no such pool")):
            call_command("sync_ce_project")

        assert CodeEngineProject.objects.get(project_id="ce-1").subnet_pool_id == "subnet-1"

    def test_transient_network_error_falls_back_to_configured_id(self, settings):
        """A timeout is not an ApiException, and must still reach the fallback.

        The vendored CE client only turns SSL errors and non-2xx responses into
        ApiException, so a DNS failure or timeout arrives as a raw urllib3 error. That is
        precisely the case the name-beside-id rollout relies on the fallback for.
        """
        settings.CE_PROJECTS = [_project(subnet_pool_name="my-pool", subnet_pool_id="subnet-1")]
        timeout = urllib3.exceptions.ReadTimeoutError(None, "https://api.us-east.codeengine.cloud.ibm.com", "too slow")

        with patch(_SEAM, side_effect=timeout):
            call_command("sync_ce_project")

        assert CodeEngineProject.objects.get(project_id="ce-1").subnet_pool_id == "subnet-1"

    def test_dry_run_reports_a_masked_fallback_as_a_failure(self, settings):
        """A dry run fails on an unresolvable name even when a fallback id is configured.

        A real run falls back and succeeds, which is right for availability but means the
        run reports success without proving the lookup works. The dry run exists to prove
        exactly that, so it refuses to be masked — and its verdict is then readable from
        the sync status alone, with no access to the Job's logs.
        """
        settings.CE_PROJECTS = [_project(subnet_pool_name="my-pool", subnet_pool_id="subnet-1")]

        with patch(_SEAM, side_effect=ValueError("no such pool")):
            with pytest.raises(CommandError):
                call_command("sync_ce_project", "--dry-run")

        # The same config without --dry-run falls back and succeeds.
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

        with patch(_SEAM, return_value="resolved-id") as lookup:
            call_command("sync_ce_project", "--dry-run")

        lookup.assert_called_once()
        assert CodeEngineProject.objects.count() == 0

    def test_one_bad_entry_does_not_block_the_others(self, settings):
        """Every entry is attempted, and the command still fails if any did not sync."""
        settings.CE_PROJECTS = [
            _name_only(project_id="ce-bad"),
            _project(project_id="ce-good", project_name="other"),
        ]

        with patch(_SEAM, side_effect=ValueError("no such pool")):
            with pytest.raises(CommandError, match="ce-bad"):
                call_command("sync_ce_project")

        assert CodeEngineProject.objects.filter(project_id="ce-good").exists()
        assert not CodeEngineProject.objects.filter(project_id="ce-bad").exists()
