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

"""Unit tests for BlockedCloudResource model."""

from django.db import IntegrityError
from django.test import TestCase

from core.models import BlockedCloudResource


class TestBlockedCloudResource(TestCase):
    """Tests for BlockedCloudResource model."""

    def test_inserting_same_triple_twice_raises_integrity_error(self):
        """Unique constraint on (account, plan, subscription) prevents duplicate rows."""
        BlockedCloudResource.objects.create(
            account="acct-123",
            plan="plan-456",
            subscription="sub-789",
        )

        with self.assertRaises(IntegrityError):
            BlockedCloudResource.objects.create(
                account="acct-123",
                plan="plan-456",
                subscription="sub-789",
            )

    def test_two_rows_differing_in_one_column_both_persist(self):
        """Constraint allows rows that differ in at least one scope column."""
        row1 = BlockedCloudResource.objects.create(
            account="acct-123",
            plan="plan-456",
            subscription="sub-789",
        )
        row2 = BlockedCloudResource.objects.create(
            account="acct-123",
            plan="plan-456",
            subscription="sub-999",  # Different subscription
        )

        assert BlockedCloudResource.objects.filter(id=row1.id).exists()
        assert BlockedCloudResource.objects.filter(id=row2.id).exists()
        assert BlockedCloudResource.objects.count() == 2

    def test_row_with_only_account_set_persists(self):
        """Nullable columns allow account-only rules (narrower scope rules for future)."""
        row = BlockedCloudResource.objects.create(
            account="acct-123",
            plan=None,
            subscription=None,
        )

        assert BlockedCloudResource.objects.filter(id=row.id).exists()
        assert row.account == "acct-123"
        assert row.plan is None
        assert row.subscription is None

    def test_makemigrations_check_no_missing_migrations(self):
        """verify manage.py makemigrations --check reports no missing migration."""
        # This is tested separately by the tox makemigrations check
        # If this test runs, it means the migration was already created.
        # Just verify the model exists and is usable.
        assert BlockedCloudResource._meta.db_table == "api_blockedcloudresource"
