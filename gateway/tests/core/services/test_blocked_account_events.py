"""Unit tests for what the scheduler does with each blocked-account-plan event."""

import logging

import pytest

from core.ibm_cloud.event_streams.kafka_consumer import InvalidEventError
from core.services.blocked_account_events import handle_blocked_account_event

_VALID = {"account_id": "acc-1", "plan_id": "plan-1", "subscription_id": "sub-1"}
_MISSING = object()


class TestHandleBlockedAccountEvent:
    def test_a_valid_event_is_logged(self, caplog):
        event = {"account_id": "acc-1", "plan_id": "plan-1", "subscription_id": "sub-1", "deleted": True}

        with caplog.at_level(logging.INFO):
            handle_blocked_account_event(event, "acc-1", "us-east")

        assert "region=us-east" in caplog.text
        assert "account_id=acc-1" in caplog.text
        assert "plan_id=plan-1" in caplog.text
        assert "subscription_id=sub-1" in caplog.text
        assert "deleted=True" in caplog.text

    def test_deleted_defaults_to_false(self, caplog):
        event = {"account_id": "acc-1", "plan_id": "plan-1", "subscription_id": "sub-1"}

        with caplog.at_level(logging.INFO):
            handle_blocked_account_event(event, None, "us-east")

        assert "deleted=False" in caplog.text

    @pytest.mark.parametrize("field", ["account_id", "plan_id", "subscription_id"])
    @pytest.mark.parametrize("value", [_MISSING, "", None, 42])
    def test_an_event_without_a_required_field_is_invalid(self, field, value):
        event = {**_VALID}
        if value is _MISSING:
            del event[field]
        else:
            event[field] = value

        with pytest.raises(InvalidEventError, match=field):
            handle_blocked_account_event(event, "key", "us-east")

    def test_every_missing_field_is_named(self):
        with pytest.raises(InvalidEventError, match="account_id, plan_id, subscription_id"):
            handle_blocked_account_event({}, "key", "us-east")
