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

_QUANTUM = BlockedCloudResource.Source.BLOCKED_ACCOUNT_PLANS
_NON_QUANTUM = BlockedCloudResource.Source.BLOCKED_ACCOUNT_PLANS_NON_QUANTUM


class TestBlockedCloudResource(TestCase):
    """Tests for BlockedCloudResource model."""

    def test_inserting_same_rule_twice_raises_integrity_error(self):
        """The unique constraint over the scope prevents duplicate rows."""
        BlockedCloudResource.objects.create(
            account="acct-123", plan="plan-456", subscription="sub-789", source=_QUANTUM
        )

        with self.assertRaises(IntegrityError):
            BlockedCloudResource.objects.create(
                account="acct-123", plan="plan-456", subscription="sub-789", source=_QUANTUM
            )

    def test_inserting_same_rule_with_nulls_twice_raises_integrity_error(self):
        """NULL counts as equal to NULL in the unique constraint, so an account-only rule cannot repeat."""
        BlockedCloudResource.objects.create(account="acct-123", source=_QUANTUM)

        with self.assertRaises(IntegrityError):
            BlockedCloudResource.objects.create(account="acct-123", source=_QUANTUM)

    def test_the_same_scope_from_another_source_raises_integrity_error(self):
        """The source is not part of the identity: blocked by either feed is the same."""
        BlockedCloudResource.objects.create(account="acct-123", source=_QUANTUM)

        with self.assertRaises(IntegrityError):
            BlockedCloudResource.objects.create(account="acct-123", source=_NON_QUANTUM)

    def test_two_rows_differing_in_one_column_both_persist(self):
        """Constraint allows rows that differ in at least one scope column."""
        BlockedCloudResource.objects.create(
            account="acct-123", plan="plan-456", subscription="sub-789", source=_QUANTUM
        )
        BlockedCloudResource.objects.create(
            account="acct-123", plan="plan-456", subscription="sub-999", source=_QUANTUM
        )
        BlockedCloudResource.objects.create(account="acct-123", plan="plan-456", source=_QUANTUM)

        assert BlockedCloudResource.objects.count() == 3

    def test_row_with_only_account_set_persists(self):
        """Nullable columns allow account-only rules (narrower scope rules for future)."""
        row = BlockedCloudResource.objects.create(account="acct-123", source=_QUANTUM)

        row.refresh_from_db()
        assert row.account == "acct-123"
        assert row.plan is None
        assert row.subscription is None

    def test_row_without_any_scope_raises_integrity_error(self):
        """A rule must scope something: all three columns NULL would block nothing in particular."""
        with self.assertRaises(IntegrityError):
            BlockedCloudResource.objects.create(source=_QUANTUM)

    def test_str_lists_the_scope_and_the_source(self):
        row = BlockedCloudResource(account="acct-123", subscription="sub-789", source=_QUANTUM)

        assert (
            str(row) == "BlockedCloudResource(account=acct-123, subscription=sub-789, source=blocked-account-plans.v1)"
        )
