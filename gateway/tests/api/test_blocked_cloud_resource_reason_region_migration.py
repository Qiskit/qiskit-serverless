"""Tests for the 0081 migration of BlockedCloudResource rows stored before reason and region existed."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

_BEFORE = [("api", "0080_job_fleet_deleted_at_job_fleet_undeleted_idx")]
_AFTER = [("api", "0081_blockedcloudresource_reason_region")]


@pytest.mark.django_db(transaction=True)
def test_the_rows_stored_before_reason_and_region_are_deleted():
    """Migration 0081 on a non-empty table, as staging had: it migrates, leaving the table empty."""
    executor = MigrationExecutor(connection)
    executor.migrate(_BEFORE)
    old_apps = executor.loader.project_state(_BEFORE).apps
    old_apps.get_model("api", "BlockedCloudResource").objects.create(account="acc-1", plan="plan-1")

    executor = MigrationExecutor(connection)
    executor.migrate(_AFTER)
    new_apps = executor.loader.project_state(_AFTER).apps

    assert not new_apps.get_model("api", "BlockedCloudResource").objects.exists()

    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
