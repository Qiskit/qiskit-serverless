"""Unit tests for what the scheduler does with each blocked-account-plan event."""

import logging

import pytest

from core.ibm_cloud.event_streams.kafka_consumer import InvalidEventError
from core.services.blocked_account_events import handle_blocked_account_event


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

    def test_missing_optional_fields_are_logged_with_defaults(self, caplog):
        with caplog.at_level(logging.INFO):
            handle_blocked_account_event({"account_id": "acc-1"}, None, "us-east")

        assert "plan_id=None" in caplog.text
        assert "deleted=False" in caplog.text

    @pytest.mark.parametrize("event", [{}, {"account_id": ""}, {"account_id": None}, {"account_id": 42}])
    def test_an_event_without_account_id_is_invalid(self, event):
        with pytest.raises(InvalidEventError):
            handle_blocked_account_event(event, "key", "us-east")
