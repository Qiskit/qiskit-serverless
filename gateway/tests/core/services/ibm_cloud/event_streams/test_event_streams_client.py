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

"""Unit tests for KafkaEventStreamsClient."""

from __future__ import annotations

import json
import os
import uuid as uuid_module
from datetime import datetime, timezone
import pytest
from unittest.mock import MagicMock, patch

from core.domain.business_models import BusinessModel
from core.ibm_cloud.event_streams.kafka_event_streams_client import KafkaEventStreamsClient
from core.ibm_cloud.event_streams.kafka_producers import UnroutableRegionError

_CLIENT_MOD = "core.ibm_cloud.event_streams.kafka_event_streams_client"
# Producer construction now lives in KafkaProducers, not in KafkaEventStreamsClient itself, so
# Producer must be patched there for these tests, which still construct a real KafkaProducers
# via KafkaEventStreamsClient()'s default argument.
_PRODUCERS_MOD = "core.ibm_cloud.event_streams.kafka_producers"

_DEFAULT_RUNNING_STARTED_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_job(
    job_id=None,
    instance_crn="crn:v1:bluemix:public:quantum-computing:eu-de:a/abc:def::",
    business_model=BusinessModel.LICENSED,
    provider_name="ibm-dev",
    program_title="test-circuit-function",
    compute_profile="16x128",
):
    job = MagicMock()
    job.id = job_id or uuid_module.uuid4()
    job.instance_crn = instance_crn
    job.business_model = business_model
    job.compute_profile = compute_profile
    job.filler = False

    provider = MagicMock()
    provider.name = provider_name

    program = MagicMock()
    program.title = program_title
    program.provider = provider

    job.program = program
    return job


def _patch_first_running_at(mock_job_event, running_started_at=_DEFAULT_RUNNING_STARTED_AT):
    """Every test's job started running at this instant, per its JobEvent history, unless overridden."""
    mock_job_event.objects.first_running_at.return_value = running_started_at


class TestKafkaEventStreamsClient:
    def test_emit_job_started_publishes_correct_payload(self):
        job = _make_job()

        with patch(f"{_PRODUCERS_MOD}.Producer") as mock_producer_cls:
            with patch(f"{_CLIENT_MOD}.JobEvent") as mock_job_event:
                with patch(f"{_CLIENT_MOD}.uuid") as mock_uuid_mod:
                    with patch(f"{_CLIENT_MOD}.datetime") as mock_dt:
                        with patch.dict(
                            os.environ,
                            {
                                "EVENT_STREAMS_BOOTSTRAP_SERVERS": "b:9093",
                                "EVENT_STREAMS_API_KEY": "k",
                                "ENVIRONMENT": "production",
                            },
                        ):
                            _patch_first_running_at(mock_job_event)
                            fake_event_id = uuid_module.UUID("00000000-0000-0000-0000-000000000001")
                            mock_uuid_mod.uuid4.return_value = fake_event_id
                            fake_now = datetime(2026, 1, 1, 12, 0, 1, tzinfo=timezone.utc)
                            mock_dt.now.return_value = fake_now

                            client = KafkaEventStreamsClient()
                            mock_producer = mock_producer_cls.return_value
                            mock_producer.flush.return_value = 0
                            client.emit_job_started(job)

        call_kwargs = mock_producer.produce.call_args[1]
        published = json.loads(call_kwargs["value"])
        assert published["specversion"] == "1.0"
        assert published["type"] == "quantum.production.function-usage.v1"
        assert published["source"] == "qiskit-serverless/scheduler/fleets"
        assert published["subject"] == str(job.id)
        assert published["data"] == {
            "metric_type": "classical_16x128",
            "metric_value": 0,
            "instance_crn": job.instance_crn,
            "resource_id": str(job.id),
            "job_started": True,
            "job_completed": False,
            "job_started_at": _DEFAULT_RUNNING_STARTED_AT.isoformat(),
        }
        assert call_kwargs["key"] == str(job.id).encode("utf-8")
        mock_producer.flush.assert_called_once()

    def test_emit_job_in_progress_computes_usage_seconds(self):
        started_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        job = _make_job()

        with patch(f"{_PRODUCERS_MOD}.Producer") as mock_producer_cls:
            with patch(f"{_CLIENT_MOD}.JobEvent") as mock_job_event:
                with patch(f"{_CLIENT_MOD}.uuid") as mock_uuid_mod:
                    with patch(f"{_CLIENT_MOD}.datetime") as mock_dt:
                        with patch.dict(
                            os.environ,
                            {
                                "EVENT_STREAMS_BOOTSTRAP_SERVERS": "b:9093",
                                "EVENT_STREAMS_API_KEY": "k",
                                "ENVIRONMENT": "production",
                            },
                        ):
                            _patch_first_running_at(mock_job_event, started_at)
                            mock_uuid_mod.uuid4.return_value = uuid_module.uuid4()
                            mock_dt.now.return_value = datetime(2026, 1, 1, 12, 0, 5, tzinfo=timezone.utc)

                            client = KafkaEventStreamsClient()
                            mock_producer = mock_producer_cls.return_value
                            mock_producer.flush.return_value = 0
                            client.emit_job_in_progress(job)

        published = json.loads(mock_producer.produce.call_args[1]["value"])
        assert published["data"]["metric_type"] == "classical_16x128"
        assert published["data"]["metric_value"] == 5
        assert published["data"]["job_started"] is False
        assert published["data"]["job_completed"] is False
        assert published["data"]["job_started_at"] == started_at.isoformat()

    def test_emit_raises_when_flush_times_out(self):
        job = _make_job()

        with patch(f"{_PRODUCERS_MOD}.Producer") as mock_producer_cls:
            with patch(f"{_CLIENT_MOD}.JobEvent") as mock_job_event:
                with patch(f"{_CLIENT_MOD}.uuid"):
                    with patch(f"{_CLIENT_MOD}.datetime") as mock_dt:
                        with patch.dict(
                            os.environ,
                            {
                                "EVENT_STREAMS_BOOTSTRAP_SERVERS": "b:9093",
                                "EVENT_STREAMS_API_KEY": "k",
                                "ENVIRONMENT": "production",
                            },
                        ):
                            _patch_first_running_at(mock_job_event)
                            mock_dt.now.return_value = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
                            client = KafkaEventStreamsClient()
                            mock_producer = mock_producer_cls.return_value
                            mock_producer.flush.return_value = 1  # 1 message undelivered

                            with pytest.raises(RuntimeError, match="not delivered after flush timeout"):
                                client.emit_job_started(job)

    def test_emit_job_in_progress_returns_zero_usage_when_running_started_at_is_none(self):
        job = _make_job()

        with patch(f"{_PRODUCERS_MOD}.Producer") as mock_producer_cls:
            with patch(f"{_CLIENT_MOD}.JobEvent") as mock_job_event:
                with patch(f"{_CLIENT_MOD}.uuid") as mock_uuid_mod:
                    with patch(f"{_CLIENT_MOD}.datetime") as mock_dt:
                        with patch.dict(
                            os.environ,
                            {
                                "EVENT_STREAMS_BOOTSTRAP_SERVERS": "b:9093",
                                "EVENT_STREAMS_API_KEY": "k",
                                "ENVIRONMENT": "production",
                            },
                        ):
                            _patch_first_running_at(mock_job_event, None)
                            mock_uuid_mod.uuid4.return_value = uuid_module.uuid4()
                            mock_dt.now.return_value = datetime(2026, 1, 1, 12, 0, 5, tzinfo=timezone.utc)

                            client = KafkaEventStreamsClient()
                            mock_producer = mock_producer_cls.return_value
                            mock_producer.flush.return_value = 0
                            client.emit_job_in_progress(job)

        published = json.loads(mock_producer.produce.call_args[1]["value"])
        assert published["data"]["metric_value"] == 0
        assert published["data"]["job_started_at"] is None

    def test_produce_failure_raises_plain_runtime_error_not_unroutable(self):
        """A producer.produce()/flush() failure is a transient Kafka outage, not a routing
        or config gap: it must stay a plain RuntimeError so it keeps tripping the caller's
        circuit breaker."""
        job = _make_job()

        with patch(f"{_PRODUCERS_MOD}.Producer") as mock_producer_cls:
            with patch(f"{_CLIENT_MOD}.JobEvent") as mock_job_event:
                with patch(f"{_CLIENT_MOD}.uuid"):
                    with patch(f"{_CLIENT_MOD}.datetime") as mock_dt:
                        with patch.dict(
                            os.environ,
                            {
                                "EVENT_STREAMS_BOOTSTRAP_SERVERS": "b:9093",
                                "EVENT_STREAMS_API_KEY": "k",
                                "ENVIRONMENT": "production",
                                "EVENT_STREAMS_MAIN_REGION": "eu-de",
                            },
                            clear=True,
                        ):
                            _patch_first_running_at(mock_job_event)
                            mock_dt.now.return_value = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
                            client = KafkaEventStreamsClient()
                            mock_producer = mock_producer_cls.return_value
                            mock_producer.produce.side_effect = Exception("broker unreachable")

                            with pytest.raises(RuntimeError, match="Failed to publish event") as exc_info:
                                client.emit_job_started(job, "classical_24x120")
                            assert not isinstance(exc_info.value, UnroutableRegionError)

    def test_filler_job_publishes_nothing(self):
        """A filler job generates no usage events: the base class short-circuits both emits."""
        job = _make_job()
        job.filler = True

        with patch(f"{_PRODUCERS_MOD}.Producer") as mock_producer_cls:
            with patch(f"{_CLIENT_MOD}.JobEvent") as mock_job_event:
                with patch(f"{_CLIENT_MOD}.uuid"):
                    with patch(f"{_CLIENT_MOD}.datetime") as mock_dt:
                        with patch.dict(
                            os.environ,
                            {
                                "EVENT_STREAMS_BOOTSTRAP_SERVERS": "b:9093",
                                "EVENT_STREAMS_API_KEY": "k",
                                "ENVIRONMENT": "production",
                            },
                        ):
                            _patch_first_running_at(mock_job_event)
                            mock_dt.now.return_value = datetime(2026, 1, 1, 12, 0, 1, tzinfo=timezone.utc)

                            client = KafkaEventStreamsClient()
                            mock_producer = mock_producer_cls.return_value
                            mock_producer.flush.return_value = 0

                            client.emit_job_started(job)
                            client.emit_job_in_progress(job)

        mock_producer.produce.assert_not_called()
