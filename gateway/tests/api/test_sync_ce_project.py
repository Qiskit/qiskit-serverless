# This code is part of a Qiskit project.
#
# (C) IBM 2026
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Tests for sync_ce_project management command."""

import pytest

from api.management.commands.sync_ce_project import _upsert_project
from core.models import CodeEngineProject


def _make_project_data(**overrides):
    """Build a valid CE_PROJECTS entry dict."""
    data = {
        "project_id": "test-project-id",
        "project_name": "test-project",
        "region": "us-east",
        "resource_group_id": "rg-123",
        "subnet_pool_id": "subnet-123",
        "pds_name_state": "state-pds",
        "pds_name_users": "user-pds",
        "pds_name_providers": "provider-pds",
        "cos_instance_name": "cos-instance",
        "cos_key_name": "cos-key",
        "cos_bucket_task_store_name": "task-bucket",
        "cos_bucket_user_data_name": "user-bucket",
        "cos_bucket_provider_data_name": "provider-bucket",
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
class TestUpsertProject:
    """Tests for _upsert_project."""

    def test_creates_new_project(self):
        """Creates a CodeEngineProject when none exists."""
        data = _make_project_data()
        result = _upsert_project("test-project-id", data)

        assert result is True
        project = CodeEngineProject.objects.get(project_id="test-project-id")
        assert project.project_name == "test-project"
        assert project.region == "us-east"
        assert project.active is True

    def test_updates_existing_project(self):
        """Updates an existing CodeEngineProject."""
        data = _make_project_data()
        _upsert_project("test-project-id", data)

        data["region"] = "eu-de"
        _upsert_project("test-project-id", data)

        project = CodeEngineProject.objects.get(project_id="test-project-id")
        assert project.region == "eu-de"

    def test_removes_duplicates_and_recreates(self):
        """Removes all existing rows with same project_id and creates fresh."""
        data = _make_project_data()
        CodeEngineProject.objects.create(
            project_id="test-project-id", zone="us-east-1", **{k: data[k] for k in data if k != "project_id"}
        )
        CodeEngineProject.objects.create(
            project_id="test-project-id", zone="us-east-2", **{k: data[k] for k in data if k != "project_id"}
        )

        assert CodeEngineProject.objects.filter(project_id="test-project-id").count() == 2

        result = _upsert_project("test-project-id", data)

        assert result is True
        assert CodeEngineProject.objects.filter(project_id="test-project-id").count() == 1
        project = CodeEngineProject.objects.get(project_id="test-project-id")
        assert project.zone is None

    def test_returns_false_on_missing_fields(self):
        """Returns False when required fields are missing."""
        data = {"project_name": "incomplete"}
        result = _upsert_project("test-project-id", data)
        assert result is False
