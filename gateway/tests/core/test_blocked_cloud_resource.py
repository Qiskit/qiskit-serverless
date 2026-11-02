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
from django.db.models import Q
from django.test import TestCase

from core.config_key import ConfigKey
from core.models import BlockedCloudResource, Config, Job
from tests.utils import TestUtils

_RESOURCE = {"account": "acct-123", "plan": "plan-456", "subscription": "sub-789"}
_US_EAST_CRN = "crn:v1:bluemix:public:quantum-computing:us-east:a/acct-123:instance-1::"
_EU_DE_CRN = "crn:v1:bluemix:public:quantum-computing:eu-de:a/acct-123:instance-1::"


class TestBlockedCloudResource(TestCase):
    """Tests for BlockedCloudResource model."""

    def setUp(self):
        Config.add_defaults()
        Config.set(ConfigKey.BLOCKED_JOBS_STOP_ENABLED, "true")

    def test_inserting_same_rule_twice_raises_integrity_error(self):
        """The unique constraint over the scope prevents duplicate rows."""
        BlockedCloudResource.objects.create(account="acct-123", plan="plan-456", subscription="sub-789")

        with self.assertRaises(IntegrityError):
            BlockedCloudResource.objects.create(account="acct-123", plan="plan-456", subscription="sub-789")

    def test_inserting_same_rule_with_nulls_twice_raises_integrity_error(self):
        """NULL counts as equal to NULL in the unique constraint, so an account-only rule cannot repeat."""
        BlockedCloudResource.objects.create(account="acct-123")

        with self.assertRaises(IntegrityError):
            BlockedCloudResource.objects.create(account="acct-123")

    def test_two_rows_differing_in_one_column_both_persist(self):
        """Constraint allows rows that differ in at least one scope column."""
        BlockedCloudResource.objects.create(account="acct-123", plan="plan-456", subscription="sub-789")
        BlockedCloudResource.objects.create(account="acct-123", plan="plan-456", subscription="sub-999")
        BlockedCloudResource.objects.create(account="acct-123", plan="plan-456")

        assert BlockedCloudResource.objects.count() == 3

    def test_row_with_only_account_set_persists(self):
        """Nullable columns allow account-only rules (narrower scope rules for future)."""
        row = BlockedCloudResource.objects.create(account="acct-123")

        row.refresh_from_db()
        assert row.account == "acct-123"
        assert row.plan is None
        assert row.subscription is None

    def test_row_without_any_scope_raises_integrity_error(self):
        """A rule must scope something: all three columns NULL would block nothing in particular."""
        with self.assertRaises(IntegrityError):
            BlockedCloudResource.objects.create()

    def test_the_same_resource_for_another_reason_or_region_is_another_row(self):
        """One limit or region lifting its block must not lift another's, so each keeps its own row."""
        resource = {"account": "acct-123", "plan": "plan-456", "subscription": "sub-789"}
        BlockedCloudResource.objects.create(**resource, reason=BlockedCloudResource.TOTAL, region="us-east")
        BlockedCloudResource.objects.create(**resource, reason=BlockedCloudResource.NON_QUANTUM, region="us-east")
        BlockedCloudResource.objects.create(**resource, reason=BlockedCloudResource.TOTAL, region="eu-de")

        assert BlockedCloudResource.objects.count() == 3

    def test_str_lists_the_populated_columns(self):
        row = BlockedCloudResource(account="acct-123", subscription="sub-789", reason="total", region="us-east")

        assert str(row) == "BlockedCloudResource(account=acct-123, subscription=sub-789, reason=total, region=us-east)"

    def test_blocked_jobs_filter_has_one_term_per_resource(self):
        """A resource blocked for two reasons is matched once, not once per row."""
        resource = {"account": "acct-123", "plan": "plan-456", "subscription": "sub-789"}
        BlockedCloudResource.objects.create(**resource, reason=BlockedCloudResource.TOTAL, region="us-east")
        BlockedCloudResource.objects.create(**resource, reason=BlockedCloudResource.NON_QUANTUM, region="us-east")

        assert BlockedCloudResource.blocked_jobs_filter() == Q(
            account_id="acct-123", plan_id="plan-456", subscription_id="sub-789"
        )

    def test_blocks_the_exact_account_plan_and_subscription(self):
        BlockedCloudResource.objects.create(account="acct-123", plan="plan-456", subscription="sub-789")

        assert BlockedCloudResource.blocks("acct-123", "plan-456", "sub-789", None)
        assert not BlockedCloudResource.blocks("acct-123", "plan-other", "sub-789", None)
        assert not BlockedCloudResource.blocks("acct-123", "plan-456", "sub-other", None)

    def test_a_null_column_only_matches_a_null_column(self):
        """Exact match: a row's NULL is not a wildcard, and neither is a job's."""
        BlockedCloudResource.objects.create(account="acct-123", plan="plan-456", subscription="sub-789")
        BlockedCloudResource.objects.create(account="acct-999")

        assert not BlockedCloudResource.blocks("acct-123", "plan-456", None, None)
        assert not BlockedCloudResource.blocks("acct-999", "plan-456", "sub-789", None)
        assert BlockedCloudResource.blocks("acct-999", None, None, None)

    def test_nothing_is_blocked_while_blocked_resources_are_not_enforced(self):
        """The rows are kept, but neither blocks() nor blocked_jobs_filter() acts on them."""
        BlockedCloudResource.objects.create(account="acct-123", plan="plan-456", subscription="sub-789")
        Config.set(ConfigKey.BLOCKED_JOBS_STOP_ENABLED, "false")

        assert not BlockedCloudResource.blocks("acct-123", "plan-456", "sub-789", None)
        assert BlockedCloudResource.blocked_jobs_filter() is None


class TestBlockedCloudResourceRegional(TestCase):
    """With regional matching on, a row only blocks the jobs whose instance CRN is in its region."""

    def setUp(self):
        Config.add_defaults()
        Config.set(ConfigKey.BLOCKED_JOBS_STOP_ENABLED, "true")
        Config.set(ConfigKey.BLOCKED_RESOURCES_REGIONAL, "true")
        BlockedCloudResource.objects.create(**_RESOURCE, reason=BlockedCloudResource.TOTAL, region="us-east")

    def _job(self, instance_crn):
        user = TestUtils.get_user_and_username(f"user-{Job.objects.count()}")[0]
        return TestUtils.create_job(
            author=user,
            program=TestUtils.create_program(program_title="Program", author=user),
            account_id="acct-123",
            plan_id="plan-456",
            subscription_id="sub-789",
            instance_crn=instance_crn,
        )

    def test_blocks_only_the_rows_region(self):
        assert BlockedCloudResource.blocks("acct-123", "plan-456", "sub-789", "us-east")
        assert not BlockedCloudResource.blocks("acct-123", "plan-456", "sub-789", "eu-de")

    def test_blocked_jobs_filter_matches_the_jobs_blocks_would_block(self):
        regions = {
            _US_EAST_CRN: "us-east",
            _EU_DE_CRN: "eu-de",
            "crn:v1:bluemix:public:quantum-computing:us-east-2:a/acct-123:instance-1::": "us-east-2",
        }
        jobs = {crn: self._job(crn) for crn in regions}

        blocked = set(Job.objects.filter(BlockedCloudResource.blocked_jobs_filter()))

        assert blocked == {jobs[_US_EAST_CRN]}
        for crn, job in jobs.items():
            assert (job in blocked) == BlockedCloudResource.blocks("acct-123", "plan-456", "sub-789", regions[crn])

    def test_blocked_jobs_filter_has_one_term_per_resource_and_region(self):
        """A resource blocked for two reasons in one region is matched once."""
        BlockedCloudResource.objects.create(**_RESOURCE, reason=BlockedCloudResource.NON_QUANTUM, region="us-east")
        BlockedCloudResource.objects.create(**_RESOURCE, reason=BlockedCloudResource.TOTAL, region="eu-de")
        us_east, eu_de = self._job(_US_EAST_CRN), self._job(_EU_DE_CRN)

        assert len(BlockedCloudResource.blocked_jobs_filter()) == 2
        assert set(Job.objects.filter(BlockedCloudResource.blocked_jobs_filter())) == {us_east, eu_de}

    def test_turning_it_off_matches_every_region_again(self):
        Config.set(ConfigKey.BLOCKED_RESOURCES_REGIONAL, "false")

        assert BlockedCloudResource.blocks("acct-123", "plan-456", "sub-789", "eu-de")
