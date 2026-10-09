"""Unit tests for what the scheduler does with each blocked-account-plan event: keep
BlockedCloudResource a mirror of the blocked set."""

import pytest

from core.ibm_cloud.event_streams.kafka_consumer import InvalidEventError
from core.models import BlockedCloudResource
from core.services.blocked_account_events import handle_blocked_account_event

_QUANTUM = "quantum.production.blocked-account-plans.v1"
_NON_QUANTUM = "quantum.production.blocked-account-plans-non-quantum.v1"


def _event(account="acc-1", plan="plan-1", subscription="sub-1", **extra) -> dict:
    return {"account_id": account, "plan_id": plan, "subscription_id": subscription, **extra}


def _handle(payload: dict, topic: str = _QUANTUM) -> None:
    handle_blocked_account_event(payload, "key", "us-east", topic)


def _rows() -> list[tuple]:
    return sorted(BlockedCloudResource.objects.values_list("account", "plan", "subscription", "source"))


@pytest.mark.django_db
class TestBlock:
    @pytest.mark.parametrize("extra", [{}, {"deleted": False}, {"deleted": None}])
    def test_an_event_not_deleted_blocks_the_resource(self, extra):
        _handle(_event(**extra))

        assert _rows() == [("acc-1", "plan-1", "sub-1", "blocked-account-plans.v1")]

    def test_the_same_event_twice_leaves_one_row(self):
        _handle(_event())
        _handle(_event())

        assert len(_rows()) == 1

    def test_the_same_event_twice_with_null_scopes_leaves_one_row(self):
        _handle(_event(plan=None, subscription=None))
        _handle(_event(plan=None, subscription=None))

        assert _rows() == [("acc-1", None, None, "blocked-account-plans.v1")]

    def test_an_empty_string_is_stored_as_null(self):
        _handle(_event(plan="", subscription=None))
        _handle(_event(plan=None, subscription=""))

        assert _rows() == [("acc-1", None, None, "blocked-account-plans.v1")]

    def test_missing_scope_fields_are_null(self):
        _handle({"subscription_id": "sub-1"})

        assert _rows() == [(None, None, "sub-1", "blocked-account-plans.v1")]

    def test_either_topic_produces_the_same_row_shape(self):
        _handle(_event(), topic=_QUANTUM)
        _handle(_event(), topic=_NON_QUANTUM)

        assert _rows() == [
            ("acc-1", "plan-1", "sub-1", "blocked-account-plans-non-quantum.v1"),
            ("acc-1", "plan-1", "sub-1", "blocked-account-plans.v1"),
        ]

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

    def test_a_deleted_event_with_null_scopes_removes_the_row(self):
        _handle(_event(plan=None, subscription=None))
        _handle(_event(plan=None, subscription=None, deleted=True))

        assert not _rows()

    def test_a_deleted_event_for_an_absent_key_is_a_no_op(self):
        _handle(_event(subscription="other"))
        _handle(_event(deleted=True))

        assert _rows() == [("acc-1", "plan-1", "other", "blocked-account-plans.v1")]

    def test_a_deleted_event_only_removes_its_topics_row(self):
        """Blocked by both topics and recovered in one: still blocked by the other."""
        _handle(_event(), topic=_QUANTUM)
        _handle(_event(), topic=_NON_QUANTUM)
        _handle(_event(deleted=True), topic=_QUANTUM)

        assert _rows() == [("acc-1", "plan-1", "sub-1", "blocked-account-plans-non-quantum.v1")]

    def test_a_deleted_event_does_not_widen_to_a_broader_scope(self):
        """Unblocking account-only does not remove a subscription-scoped rule of that account."""
        _handle(_event(plan=None, subscription=None))
        _handle(_event())
        _handle(_event(plan=None, subscription=None, deleted=True))

        assert _rows() == [("acc-1", "plan-1", "sub-1", "blocked-account-plans.v1")]


@pytest.mark.django_db
class TestInvalid:
    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"deleted": False},
            _event(account=None, plan=None, subscription=None),
            _event(account="", plan="", subscription=""),
        ],
    )
    def test_an_event_without_any_scope_is_invalid(self, payload):
        with pytest.raises(InvalidEventError, match="no account_id, plan_id nor subscription_id"):
            _handle(payload)

        assert not _rows()

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

    def test_an_unknown_topic_is_invalid(self):
        with pytest.raises(InvalidEventError, match="not a blocked-account-plan topic"):
            _handle(_event(), topic="quantum.production.something-else.v1")

        assert not _rows()
