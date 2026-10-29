"""Unit tests for what the scheduler does with each blocked-account-plan event: keep
BlockedCloudResource a mirror of the blocked set."""

import pytest

from core.config_key import ConfigKey
from core.ibm_cloud.event_streams.kafka_consumer import InvalidEventError
from core.models import BlockedCloudResource, Config
from core.services.blocked_account_events import BlockedAccountEventsService

_MISSING = object()


def _event(account="acc-1", plan="plan-1", subscription="sub-1", **extra) -> dict:
    return {"account_id": account, "plan_id": plan, "subscription_id": subscription, **extra}


_TOTAL_TOPIC = "total-topic"
_NON_QUANTUM_TOPIC = "non-quantum-topic"
_TOPIC_REASONS = {_TOTAL_TOPIC: BlockedCloudResource.TOTAL, _NON_QUANTUM_TOPIC: BlockedCloudResource.NON_QUANTUM}


def _handle(payload: dict, topic: str = _TOTAL_TOPIC, region: str = "us-east") -> None:
    BlockedAccountEventsService(_TOPIC_REASONS).handle(payload, "key", region, topic)


def _rows() -> list[tuple]:
    return sorted(BlockedCloudResource.objects.values_list("account", "plan", "subscription"))


def _reasons_and_regions() -> list[tuple]:
    return sorted(BlockedCloudResource.objects.values_list("reason", "region"))


@pytest.mark.django_db
class TestBlock:
    @pytest.mark.parametrize("extra", [{}, {"deleted": False}, {"deleted": None}])
    def test_an_event_not_deleted_blocks_the_resource(self, extra):
        _handle(_event(**extra))

        assert _rows() == [("acc-1", "plan-1", "sub-1")]

    def test_the_same_event_twice_leaves_one_row(self):
        _handle(_event())
        _handle(_event())

        assert len(_rows()) == 1

    def test_a_different_scope_is_another_row(self):
        _handle(_event(subscription="sub-1"))
        _handle(_event(subscription="sub-2"))

        assert len(_rows()) == 2

    def test_the_account_is_stored_without_its_prefix(self):
        """Jobs store the bare account id from the IAM token, so the row must match it."""
        _handle(_event(account="a/acc-1"))

        assert _rows() == [("acc-1", "plan-1", "sub-1")]


@pytest.mark.django_db
class TestUnblock:
    def test_a_deleted_event_removes_the_row(self):
        _handle(_event())
        _handle(_event(deleted=True))

        assert not _rows()

    def test_a_deleted_event_for_an_absent_key_is_a_no_op(self):
        _handle(_event(subscription="other"))
        _handle(_event(deleted=True))

        assert _rows() == [("acc-1", "plan-1", "other")]

    def test_a_prefixed_deleted_event_removes_the_row(self):
        _handle(_event(account="a/acc-1"))
        _handle(_event(account="a/acc-1", deleted=True))

        assert not _rows()


@pytest.mark.django_db
class TestReasonsAndRegions:
    """Each limit and each region blocks on its own: a resource runs again only once every one has lifted."""

    def test_the_row_keeps_its_topics_reason_and_its_region(self):
        _handle(_event(), topic=_NON_QUANTUM_TOPIC, region="eu-de")

        assert _reasons_and_regions() == [("non_quantum", "eu-de")]

    def test_both_limits_blocking_leave_a_row_each(self):
        _handle(_event(), topic=_TOTAL_TOPIC)
        _handle(_event(), topic=_NON_QUANTUM_TOPIC)

        assert _reasons_and_regions() == [("non_quantum", "us-east"), ("total", "us-east")]

    @pytest.mark.parametrize("lifted, still_blocking", [(_TOTAL_TOPIC, "non_quantum"), (_NON_QUANTUM_TOPIC, "total")])
    def test_lifting_one_limit_keeps_the_other_blocking(self, lifted, still_blocking):
        Config.set(ConfigKey.BLOCKED_JOBS_STOP_ENABLED, "true")
        _handle(_event(), topic=_TOTAL_TOPIC)
        _handle(_event(), topic=_NON_QUANTUM_TOPIC)

        _handle(_event(deleted=True), topic=lifted)

        assert _reasons_and_regions() == [(still_blocking, "us-east")]
        assert BlockedCloudResource.blocks("acc-1", "plan-1", "sub-1")

    def test_lifting_both_limits_unblocks_the_resource(self):
        _handle(_event(), topic=_TOTAL_TOPIC)
        _handle(_event(), topic=_NON_QUANTUM_TOPIC)

        _handle(_event(deleted=True), topic=_NON_QUANTUM_TOPIC)
        _handle(_event(deleted=True), topic=_TOTAL_TOPIC)

        assert not BlockedCloudResource.blocks("acc-1", "plan-1", "sub-1")

    def test_an_unblock_in_one_region_keeps_another_regions_block(self):
        _handle(_event(), region="us-east")
        _handle(_event(), region="eu-de")

        _handle(_event(deleted=True), region="us-east")

        assert _reasons_and_regions() == [("total", "eu-de")]

    @pytest.mark.parametrize("topic", [_TOTAL_TOPIC, _NON_QUANTUM_TOPIC])
    def test_the_same_event_twice_for_a_reason_leaves_one_row(self, topic):
        _handle(_event(), topic=topic)
        _handle(_event(), topic=topic)

        assert len(_reasons_and_regions()) == 1

    def test_an_unblock_in_a_region_without_a_row_is_a_no_op(self):
        _handle(_event(), region="us-east")

        _handle(_event(deleted=True), region="eu-de")

        assert _reasons_and_regions() == [("total", "us-east")]

    def test_an_event_from_a_topic_without_a_reason_is_invalid(self):
        with pytest.raises(InvalidEventError, match="no blocking reason"):
            _handle(_event(), topic="unknown-topic")

        assert not _rows()


@pytest.mark.django_db
class TestInvalid:
    @pytest.mark.parametrize("field", ["account_id", "plan_id", "subscription_id"])
    @pytest.mark.parametrize("value", [_MISSING, "", None])
    def test_an_event_without_a_required_field_is_invalid(self, field, value):
        event = _event()
        if value is _MISSING:
            del event[field]
        else:
            event[field] = value

        with pytest.raises(InvalidEventError, match=field):
            _handle(event)

        assert not _rows()

    def test_an_account_that_is_only_the_prefix_is_missing(self):
        with pytest.raises(InvalidEventError, match="account_id"):
            _handle(_event(account="a/"))

        assert not _rows()

    def test_every_missing_field_is_named(self):
        with pytest.raises(InvalidEventError, match="account_id, plan_id, subscription_id"):
            _handle({})

    @pytest.mark.parametrize(
        "payload",
        [_event(account=42), _event(plan=["p"]), _event(subscription={"id": "s"})],
    )
    def test_a_scope_field_that_is_not_a_string_is_invalid(self, payload):
        with pytest.raises(InvalidEventError, match="not a string"):
            _handle(payload)

    def test_a_scope_field_too_long_to_store_is_invalid(self):
        with pytest.raises(InvalidEventError, match="longer than 255"):
            _handle(_event(account="a" * 256))

    @pytest.mark.parametrize("deleted", ["true", 1, 0])
    def test_a_deleted_that_is_not_a_boolean_is_invalid(self, deleted):
        _handle(_event())

        with pytest.raises(InvalidEventError, match="not a boolean"):
            _handle(_event(deleted=deleted))

        assert len(_rows()) == 1
