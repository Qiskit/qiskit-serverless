"""Unit tests for what the scheduler does with each blocked-account-plan event: keep
BlockedCloudResource a mirror of the blocked set."""

import pytest

from core.ibm_cloud.event_streams.kafka_consumer import InvalidEventError
from core.models import BlockedCloudResource
from core.services.blocked_account_events import BlockedAccountEventsService

_MISSING = object()


def _event(account="acc-1", plan="plan-1", subscription="sub-1", **extra) -> dict:
    return {"account_id": account, "plan_id": plan, "subscription_id": subscription, **extra}


def _handle(payload: dict) -> None:
    BlockedAccountEventsService().handle(payload, "key", "us-east")


def _rows() -> list[tuple]:
    return sorted(BlockedCloudResource.objects.values_list("account", "plan", "subscription"))


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
