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

"""Tests for the retryable migration operations."""

import pytest
from django.db import connection, models
from django.db.migrations.loader import MigrationLoader

from core.migration_operations import AddIndexConcurrentlyRetryable


@pytest.mark.django_db(transaction=True)
def test_add_index_falls_back_to_plain_add_index_off_postgres():
    """Off PostgreSQL the operation builds the index without CONCURRENTLY."""
    if connection.vendor == "postgresql":
        pytest.skip("covers the non-PostgreSQL fallback")

    operation = AddIndexConcurrentlyRetryable(
        model_name="job",
        index=models.Index(fields=["fleet_id"], name="job_retryable_test_idx"),
    )
    from_state = MigrationLoader(connection).project_state()
    to_state = from_state.clone()
    operation.state_forwards("api", to_state)

    with connection.schema_editor() as editor:
        operation.database_forwards("api", editor, from_state, to_state)

    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, "api_job")
    assert "job_retryable_test_idx" in constraints
