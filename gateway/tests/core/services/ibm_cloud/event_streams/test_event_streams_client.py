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

"""Unit tests for IBMEventStreamsClient."""

from __future__ import annotations

import json
import os
import uuid as uuid_module
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from core.ibm_cloud.event_streams.event_streams_client import IBMEventStreamsClient

_CLIENT_MOD = "core.ibm_cloud.event_streams.event_streams_client"


def _make_job(
    job_id=None,
    instance_crn="crn:v1:bluemix:public:quantum-computing:us-east:a/abc:def::",
    running_started_at=None,
):
    job = MagicMock()
    job.id = job_id or uuid_module.uuid4()
    job.instance_crn = instance_crn
    job.running_started_at = running_started_at or datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return job


class TestIBMEventStreamsClient:
    def test_producer_configured_with_sasl_plain_tls(self):
        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
            with patch.dict(
                os.environ,
                {
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS": "broker1:9093",
                    "EVENT_STREAMS_API_KEY": "my-key",
                    "ENVIRONMENT": "staging",
                },
            ):
                IBMEventStreamsClient()

        mock_producer_cls.assert_called_once_with({
            "bootstrap.servers": "broker1:9093",
            "security.protocol": "SASL_SSL",
            "sasl.mechanisms": "PLAIN",
            "sasl.username": "token",
            "sasl.password": "my-key",
        })

    def test_topic_constructed_from_environment(self):
        with patch(f"{_CLIENT_MOD}.Producer"):
            with patch.dict(os.environ, {
                "EVENT_STREAMS_BOOTSTRAP_SERVERS": "b:9093",
                "EVENT_STREAMS_API_KEY": "k",
                "ENVIRONMENT": "staging",
            }):
                client = IBMEventStreamsClient()

        assert client.topic == "quantum.staging.function-usage.v1"

    def test_emit_job_started_publishes_correct_payload(self):
        job = _make_job()

        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
            with patch(f"{_CLIENT_MOD}.uuid") as mock_uuid_mod:
                with patch(f"{_CLIENT_MOD}.datetime") as mock_dt:
                    with patch.dict(os.environ, {
                        "EVENT_STREAMS_BOOTSTRAP_SERVERS": "b:9093",
                        "EVENT_STREAMS_API_KEY": "k",
                        "ENVIRONMENT": "production",
                    }):
                        fake_event_id = uuid_module.UUID("00000000-0000-0000-0000-000000000001")
                        mock_uuid_mod.uuid4.return_value = fake_event_id
                        fake_now = datetime(2026, 1, 1, 12, 0, 1, tzinfo=timezone.utc)
                        mock_dt.now.return_value = fake_now

                        client = IBMEventStreamsClient()
                        mock_producer = mock_producer_cls.return_value
                        mock_producer.flush.return_value = 0
                        client.emit_job_started(job)

        published = json.loads(mock_producer.produce.call_args[1]["value"])
        assert published["specversion"] == "1.0"
        assert published["type"] == "quantum.production.function-usage.v1"
        assert published["source"] == "qiskit-serverless/scheduler/fleets"
        assert published["subject"] == str(job.id)
        assert published["data"]["event_type"] == "job_started"
        assert published["data"]["usage_nanoseconds"] == 0
        assert published["data"]["instance_crn"] == job.instance_crn
        mock_producer.flush.assert_called_once()

    def test_emit_job_in_progress_computes_usage_nanoseconds(self):
        started_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        job = _make_job(running_started_at=started_at)

        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
            with patch(f"{_CLIENT_MOD}.uuid") as mock_uuid_mod:
                with patch(f"{_CLIENT_MOD}.datetime") as mock_dt:
                    with patch.dict(os.environ, {
                        "EVENT_STREAMS_BOOTSTRAP_SERVERS": "b:9093",
                        "EVENT_STREAMS_API_KEY": "k",
                        "ENVIRONMENT": "production",
                    }):
                        mock_uuid_mod.uuid4.return_value = uuid_module.uuid4()
                        mock_dt.now.return_value = datetime(2026, 1, 1, 12, 0, 5, tzinfo=timezone.utc)

                        client = IBMEventStreamsClient()
                        mock_producer = mock_producer_cls.return_value
                        mock_producer.flush.return_value = 0
                        client.emit_job_in_progress(job)

        published = json.loads(mock_producer.produce.call_args[1]["value"])
        assert published["data"]["event_type"] == "job_in_progress"
        assert published["data"]["usage_nanoseconds"] == 5_000_000_000

    def test_emit_job_ended_computes_usage_nanoseconds(self):
        started_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        job = _make_job(running_started_at=started_at)

        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
            with patch(f"{_CLIENT_MOD}.uuid") as mock_uuid_mod:
                with patch(f"{_CLIENT_MOD}.datetime") as mock_dt:
                    with patch.dict(os.environ, {
                        "EVENT_STREAMS_BOOTSTRAP_SERVERS": "b:9093",
                        "EVENT_STREAMS_API_KEY": "k",
                        "ENVIRONMENT": "production",
                    }):
                        mock_uuid_mod.uuid4.return_value = uuid_module.uuid4()
                        mock_dt.now.return_value = datetime(2026, 1, 1, 12, 0, 30, tzinfo=timezone.utc)

                        client = IBMEventStreamsClient()
                        mock_producer = mock_producer_cls.return_value
                        mock_producer.flush.return_value = 0
                        client.emit_job_ended(job)

        published = json.loads(mock_producer.produce.call_args[1]["value"])
        assert published["data"]["event_type"] == "job_ended"
        assert published["data"]["usage_nanoseconds"] == 30_000_000_000

    def test_emit_job_in_progress_returns_zero_usage_when_running_started_at_is_none(self):
        job = _make_job(running_started_at=None)
        job.running_started_at = None  # override the default

        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
            with patch(f"{_CLIENT_MOD}.uuid") as mock_uuid_mod:
                with patch(f"{_CLIENT_MOD}.datetime") as mock_dt:
                    with patch.dict(os.environ, {
                        "EVENT_STREAMS_BOOTSTRAP_SERVERS": "b:9093",
                        "EVENT_STREAMS_API_KEY": "k",
                        "ENVIRONMENT": "production",
                    }):
                        mock_uuid_mod.uuid4.return_value = uuid_module.uuid4()
                        mock_dt.now.return_value = datetime(2026, 1, 1, 12, 0, 5, tzinfo=timezone.utc)

                        client = IBMEventStreamsClient()
                        mock_producer = mock_producer_cls.return_value
                        mock_producer.flush.return_value = 0
                        client.emit_job_in_progress(job)

        published = json.loads(mock_producer.produce.call_args[1]["value"])
        assert published["data"]["usage_nanoseconds"] == 0
