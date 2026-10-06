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

"""Unit tests for ConsumeBlockedAccountEvents scheduler task."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.tasks.consume_blocked_account_events import ConsumeBlockedAccountEvents

_TASK_MOD = "scheduler.tasks.consume_blocked_account_events"


def _make_metrics() -> SchedulerMetrics:
    """Create a mock metrics collector."""
    return MagicMock(spec=SchedulerMetrics)


def _make_kill_signal() -> KillSignal:
    """Create a KillSignal instance."""
    return KillSignal()


def test_consume_blocked_account_events_instantiation():
    """Verify task can be instantiated."""
    kill_signal = _make_kill_signal()
    metrics = _make_metrics()
    task = ConsumeBlockedAccountEvents(kill_signal, metrics)

    assert task.kill_signal is kill_signal
    assert task.metrics is metrics
    assert task.name == "ConsumeBlockedAccountEvents"


@override_settings(EVENT_STREAMS_ENABLED=True)
def test_event_streams_client_initializes_kafka_when_enabled():
    """When EVENT_STREAMS_ENABLED=True, client property returns KafkaEventStreamsClient."""
    with patch(f"{_TASK_MOD}.KafkaEventStreamsClient") as mock_kafka_cls:
        kill_signal = _make_kill_signal()
        metrics = _make_metrics()
        task = ConsumeBlockedAccountEvents(kill_signal, metrics)

        # Access property — should instantiate Kafka client
        _ = task.event_streams_client

        mock_kafka_cls.assert_called_once()


@override_settings(EVENT_STREAMS_ENABLED=False)
def test_event_streams_client_initializes_noop_when_disabled():
    """When EVENT_STREAMS_ENABLED=False, client property returns NoOpEventStreamsClient."""
    with patch(f"{_TASK_MOD}.NoOpEventStreamsClient") as mock_noop_cls:
        kill_signal = _make_kill_signal()
        metrics = _make_metrics()
        task = ConsumeBlockedAccountEvents(kill_signal, metrics)

        # Access property — should instantiate NoOp client
        _ = task.event_streams_client

        mock_noop_cls.assert_called_once()


@override_settings(EVENT_STREAMS_ENABLED=True)
def test_event_streams_client_cached():
    """Client property should cache the instance (same on repeated access)."""
    with patch(f"{_TASK_MOD}.KafkaEventStreamsClient") as mock_kafka_cls:
        kill_signal = _make_kill_signal()
        metrics = _make_metrics()
        task = ConsumeBlockedAccountEvents(kill_signal, metrics)

        client1 = task.event_streams_client
        client2 = task.event_streams_client

        # Should instantiate only once
        mock_kafka_cls.assert_called_once()
        assert client1 is client2


@override_settings(EVENT_STREAMS_ENABLED=True)
def test_run_delegates_to_event_streams_client():
    """task.run() should call event_streams_client.consume_events()."""
    with patch(f"{_TASK_MOD}.KafkaEventStreamsClient") as mock_kafka_cls:
        kill_signal = _make_kill_signal()
        metrics = _make_metrics()
        task = ConsumeBlockedAccountEvents(kill_signal, metrics)

        mock_client = MagicMock()
        mock_kafka_cls.return_value = mock_client

        task.run()

        mock_client.consume_events.assert_called_once()
