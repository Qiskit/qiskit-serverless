"""Tests for the sync_ce_project management command."""

import pytest
from django.core.management import call_command

from core.models import CodeEngineProject


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

    def test_id_only_config_still_works(self, settings):
        """A config with subnet_pool_id (no name) upserts the id as before."""
        settings.CE_PROJECTS = [_project(subnet_pool_id="subnet-1")]
        call_command("sync_ce_project")

        project = CodeEngineProject.objects.get(project_id="ce-1")
        assert project.subnet_pool_id == "subnet-1"
        assert project.subnet_pool_name is None

    def test_name_only_config_is_accepted_and_leaves_id_empty(self, settings):
        """A name-only config stores the name and leaves the id for the runner to fill."""
        entry = _project(subnet_pool_name="my-pool")
        del entry["subnet_pool_id"]
        settings.CE_PROJECTS = [entry]
        call_command("sync_ce_project")

        project = CodeEngineProject.objects.get(project_id="ce-1")
        assert project.subnet_pool_name == "my-pool"
        assert not project.subnet_pool_id

    def test_entry_with_neither_id_nor_name_is_rejected(self, settings):
        """An entry missing both subnet pool fields does not create a row."""
        entry = _project()
        del entry["subnet_pool_id"]
        settings.CE_PROJECTS = [entry]
        call_command("sync_ce_project")

        assert CodeEngineProject.objects.count() == 0

    def test_resync_preserves_cached_id_when_name_unchanged(self, settings):
        """A cached id survives re-sync of a name-only config (not blanked every boot)."""
        entry = _project(subnet_pool_name="my-pool")
        del entry["subnet_pool_id"]
        settings.CE_PROJECTS = [entry]
        call_command("sync_ce_project")

        # simulate the runner caching a resolved id
        project = CodeEngineProject.objects.get(project_id="ce-1")
        project.subnet_pool_id = "cached-id"
        project.save(update_fields=["subnet_pool_id"])

        call_command("sync_ce_project")
        project.refresh_from_db()
        assert project.subnet_pool_id == "cached-id"

    def test_resync_invalidates_cached_id_when_name_changes(self, settings):
        """Renaming the pool in config blanks the cached id so it re-resolves."""
        entry = _project(subnet_pool_name="old-pool")
        del entry["subnet_pool_id"]
        settings.CE_PROJECTS = [entry]
        call_command("sync_ce_project")

        project = CodeEngineProject.objects.get(project_id="ce-1")
        project.subnet_pool_id = "cached-id"
        project.save(update_fields=["subnet_pool_id"])

        renamed = _project(subnet_pool_name="new-pool")
        del renamed["subnet_pool_id"]
        settings.CE_PROJECTS = [renamed]
        call_command("sync_ce_project")

        project.refresh_from_db()
        assert project.subnet_pool_name == "new-pool"
        assert not project.subnet_pool_id
