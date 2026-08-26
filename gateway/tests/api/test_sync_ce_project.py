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

    def test_seeds_provider_name_when_given(self, settings):
        """An entry carrying provider_name dedicates the project to that provider."""
        settings.CE_PROJECTS = [_project(provider_name="acme")]
        call_command("sync_ce_project")

        assert CodeEngineProject.objects.get(project_id="ce-1").provider_name == "acme"

    def test_entry_without_provider_name_is_shared(self, settings):
        """An entry with no provider_name seeds the shared project."""
        settings.CE_PROJECTS = [_project()]
        call_command("sync_ce_project")

        assert CodeEngineProject.objects.get(project_id="ce-1").provider_name == ""
