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
import logging
import os
import uuid as uuid_module
from datetime import datetime, timezone
import pytest
from unittest.mock import MagicMock, patch

from core.domain.business_models import BusinessModel
from core.ibm_cloud.event_streams.kafka_event_streams_client import KafkaEventStreamsClient

_CLIENT_MOD = "core.ibm_cloud.event_streams.kafka_event_streams_client"


def _make_job(
    job_id=None,
    instance_crn="crn:v1:bluemix:public:quantum-computing:us-east:a/abc:def::",
    running_started_at=None,
    business_model=BusinessModel.LICENSED,
    provider_name="ibm-dev",
    program_title="test-circuit-function",
    compute_profile="24x120",
):
    job = MagicMock()
    job.id = job_id or uuid_module.uuid4()
    job.instance_crn = instance_crn
    job.running_started_at = running_started_at or datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
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


class TestKafkaEventStreamsClient:
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
                KafkaEventStreamsClient()

        mock_producer_cls.assert_called_once_with(
            {
                "bootstrap.servers": "broker1:9093",
                "security.protocol": "SASL_SSL",
                "sasl.mechanisms": "PLAIN",
                "sasl.username": "token",
                "sasl.password": "my-key",
                "enable.idempotence": True,
                "acks": "all",
            }
        )

    def test_topic_constructed_from_environment(self):
        with patch(f"{_CLIENT_MOD}.Producer"):
            with patch.dict(
                os.environ,
                {
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS": "b:9093",
                    "EVENT_STREAMS_API_KEY": "k",
                    "ENVIRONMENT": "staging",
                },
            ):
                client = KafkaEventStreamsClient()

        assert client.topic == "quantum.staging.function-usage.v1"

    def test_custom_user_in_default_region(self):
        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
            with patch.dict(
                os.environ,
                {
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS": "broker1:9093",
                    "EVENT_STREAMS_API_KEY": "my-key",
                    "EVENT_STREAMS_USER": "custom-user",
                    "ENVIRONMENT": "staging",
                },
            ):
                KafkaEventStreamsClient()

        mock_producer_cls.assert_called_once_with(
            {
                "bootstrap.servers": "broker1:9093",
                "security.protocol": "SASL_SSL",
                "sasl.mechanisms": "PLAIN",
                "sasl.username": "custom-user",
                "sasl.password": "my-key",
                "enable.idempotence": True,
                "acks": "all",
            }
        )

    def test_custom_user_in_regional_producer(self):
        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
            with patch.dict(
                os.environ,
                {
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS": "broker-us:9093",
                    "EVENT_STREAMS_API_KEY": "us-key",
                    "EVENT_STREAMS_USER": "default-user",
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS_EU_DE": "broker-eu:9093",
                    "EVENT_STREAMS_API_KEY_EU_DE": "eu-key",
                    "EVENT_STREAMS_USER_EU_DE": "custom-eu-user",
                    "ENVIRONMENT": "production",
                },
                clear=True,
            ):
                KafkaEventStreamsClient()

        calls = mock_producer_cls.call_args_list
        assert len(calls) == 2

        default_call = [c for c in calls if "broker-us" in str(c)][0]
        eu_call = [c for c in calls if "broker-eu" in str(c)][0]

        assert default_call[0][0]["sasl.username"] == "default-user"
        assert eu_call[0][0]["sasl.username"] == "custom-eu-user"

    def test_emit_job_started_publishes_correct_payload(self):
        job = _make_job()

        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
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
            "metric_type": "classical_ibm-dev_test-circuit-function_24x120",
            "metric_value": 0,
            "instance_crn": job.instance_crn,
            "resource_id": str(job.id),
            "job_started": True,
            "job_completed": False,
            "job_started_at": job.running_started_at.isoformat(),
        }
        assert call_kwargs["key"] == str(job.id).encode("utf-8")
        mock_producer.flush.assert_called_once()

    def test_emit_job_in_progress_computes_usage_milliseconds(self):
        started_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        job = _make_job(running_started_at=started_at)

        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
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
                        mock_uuid_mod.uuid4.return_value = uuid_module.uuid4()
                        mock_dt.now.return_value = datetime(2026, 1, 1, 12, 0, 5, tzinfo=timezone.utc)

                        client = KafkaEventStreamsClient()
                        mock_producer = mock_producer_cls.return_value
                        mock_producer.flush.return_value = 0
                        client.emit_job_in_progress(job)

        published = json.loads(mock_producer.produce.call_args[1]["value"])
        assert published["data"]["metric_type"] == "classical_ibm-dev_test-circuit-function_24x120"
        assert published["data"]["metric_value"] == 5_000
        assert published["data"]["job_started"] is False
        assert published["data"]["job_completed"] is False
        assert published["data"]["job_started_at"] == started_at.isoformat()

    def test_emit_job_completed_computes_usage_milliseconds(self):
        started_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        job = _make_job(running_started_at=started_at)

        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
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
                        mock_uuid_mod.uuid4.return_value = uuid_module.uuid4()
                        mock_dt.now.return_value = datetime(2026, 1, 1, 12, 0, 30, tzinfo=timezone.utc)

                        client = KafkaEventStreamsClient()
                        mock_producer = mock_producer_cls.return_value
                        mock_producer.flush.return_value = 0
                        client.emit_job_completed(job)

        published = json.loads(mock_producer.produce.call_args[1]["value"])
        assert published["data"]["metric_type"] == "classical_ibm-dev_test-circuit-function_24x120"
        assert published["data"]["metric_value"] == 30_000
        assert published["data"]["job_started"] is False
        assert published["data"]["job_completed"] is True
        assert published["data"]["job_started_at"] == started_at.isoformat()

    def test_emit_raises_when_flush_times_out(self):
        job = _make_job()

        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
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
                        mock_dt.now.return_value = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
                        client = KafkaEventStreamsClient()
                        mock_producer = mock_producer_cls.return_value
                        mock_producer.flush.return_value = 1  # 1 message undelivered

                        with pytest.raises(RuntimeError, match="not delivered after flush timeout"):
                            client.emit_job_started(job)

    def test_emit_job_in_progress_returns_zero_usage_when_running_started_at_is_none(self):
        job = _make_job(running_started_at=None)
        job.running_started_at = None  # override the default

        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
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
                        mock_uuid_mod.uuid4.return_value = uuid_module.uuid4()
                        mock_dt.now.return_value = datetime(2026, 1, 1, 12, 0, 5, tzinfo=timezone.utc)

                        client = KafkaEventStreamsClient()
                        mock_producer = mock_producer_cls.return_value
                        mock_producer.flush.return_value = 0
                        client.emit_job_in_progress(job)

        published = json.loads(mock_producer.produce.call_args[1]["value"])
        assert published["data"]["metric_value"] == 0
        assert published["data"]["job_started_at"] is None

    def test_emit_license_fee_publishes_correct_payload(self):
        job = _make_job()
        job.program = MagicMock()
        job.program.provider.name = "ibm"
        job.program.title = "test-program"

        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
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
                        fake_event_id = uuid_module.UUID("00000000-0000-0000-0000-000000000002")
                        mock_uuid_mod.uuid4.return_value = fake_event_id
                        fake_now = datetime(2026, 1, 1, 12, 0, 1, tzinfo=timezone.utc)
                        mock_dt.now.return_value = fake_now

                        client = KafkaEventStreamsClient()
                        mock_producer = mock_producer_cls.return_value
                        mock_producer.flush.return_value = 0
                        client.emit_license_fee(job)

        call_kwargs = mock_producer.produce.call_args[1]
        published = json.loads(call_kwargs["value"])
        assert published["specversion"] == "1.0"
        assert published["type"] == "quantum.production.function-usage.v1"
        assert published["source"] == "qiskit-serverless/scheduler/fleets"
        assert published["subject"] == str(job.id)
        assert published["data"] == {
            "metric_type": "license_ibm_test-program",
            "metric_value": 1,
            "instance_crn": job.instance_crn,
            "resource_id": str(job.id),
            "job_started": True,
            "job_completed": True,
            "job_started_at": job.running_started_at.isoformat(),
            "business_model": "licensed",
        }
        assert call_kwargs["key"] == str(job.id).encode("utf-8")
        mock_producer.flush.assert_called_once()

    @pytest.mark.parametrize(
        "business_model,expected",
        [
            (BusinessModel.SUBSIDIZED, "licensed"),
            (BusinessModel.LICENSED, "licensed"),
            (BusinessModel.TRIAL, "trial"),
            (BusinessModel.CONSUMPTION, "consumption"),
        ],
    )
    def test_emit_license_fee_maps_business_model(self, business_model, expected):
        job = _make_job(business_model=business_model)
        job.program = MagicMock()
        job.program.provider.name = "ibm"
        job.program.title = "test-program"

        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
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
                        mock_dt.now.return_value = datetime(2026, 1, 1, 12, 0, 1, tzinfo=timezone.utc)

                        client = KafkaEventStreamsClient()
                        mock_producer = mock_producer_cls.return_value
                        mock_producer.flush.return_value = 0
                        client.emit_license_fee(job)

        published = json.loads(mock_producer.produce.call_args[1]["value"])
        assert published["data"]["business_model"] == expected

    def test_business_model_absent_from_non_license_events(self):
        job = _make_job()

        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
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
                        mock_dt.now.return_value = datetime(2026, 1, 1, 12, 0, 1, tzinfo=timezone.utc)

                        client = KafkaEventStreamsClient()
                        mock_producer = mock_producer_cls.return_value
                        mock_producer.flush.return_value = 0
                        client.emit_job_started(job, "classical_time")

        published = json.loads(mock_producer.produce.call_args[1]["value"])
        assert "business_model" not in published["data"]
        assert published["data"]["job_started_at"] == job.running_started_at.isoformat()

    def test_default_region_producer_from_unsuffixed_vars(self):
        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
            with patch.dict(
                os.environ,
                {
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS": "broker1:9093",
                    "EVENT_STREAMS_API_KEY": "default-key",
                    "ENVIRONMENT": "production",
                },
                clear=True,
            ):
                client = KafkaEventStreamsClient()

        assert "us-east" in client._producers
        mock_producer_cls.assert_called_once()

    def test_suffixed_vars_discovered_by_scan(self):
        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
            with patch.dict(
                os.environ,
                {
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS": "broker-us:9093",
                    "EVENT_STREAMS_API_KEY": "us-key",
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS_EU_DE": "broker-eu:9093",
                    "EVENT_STREAMS_API_KEY_EU_DE": "eu-key",
                    "ENVIRONMENT": "production",
                },
                clear=True,
            ):
                client = KafkaEventStreamsClient()

        assert "us-east" in client._producers
        assert "eu-de" in client._producers
        assert mock_producer_cls.call_count == 2

    def test_event_streams_default_region_respected(self):
        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
            with patch.dict(
                os.environ,
                {
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS": "broker1:9093",
                    "EVENT_STREAMS_API_KEY": "key",
                    "EVENT_STREAMS_DEFAULT_REGION": "eu-gb",
                    "ENVIRONMENT": "production",
                },
                clear=True,
            ):
                client = KafkaEventStreamsClient()

        assert client._default_region == "eu-gb"
        assert "eu-gb" in client._producers

    def test_routing_selects_right_producer(self):
        job_us = _make_job(instance_crn="crn:v1:bluemix:public:quantum-computing:us-east:a/abc:def::")
        job_eu = _make_job(instance_crn="crn:v1:bluemix:public:quantum-computing:eu-de:a/abc:def::")

        mock_producer_us = MagicMock()
        mock_producer_eu = MagicMock()
        mock_producer_us.flush.return_value = 0
        mock_producer_eu.flush.return_value = 0

        def create_producer_side_effect(config):
            if "broker-us" in config.get("bootstrap.servers", ""):
                return mock_producer_us
            elif "broker-eu" in config.get("bootstrap.servers", ""):
                return mock_producer_eu
            return MagicMock()

        with patch(f"{_CLIENT_MOD}.Producer", side_effect=create_producer_side_effect):
            with patch(f"{_CLIENT_MOD}.uuid"):
                with patch(f"{_CLIENT_MOD}.datetime") as mock_dt:
                    with patch.dict(
                        os.environ,
                        {
                            "EVENT_STREAMS_BOOTSTRAP_SERVERS": "broker-us:9093",
                            "EVENT_STREAMS_API_KEY": "us-key",
                            "EVENT_STREAMS_BOOTSTRAP_SERVERS_EU_DE": "broker-eu:9093",
                            "EVENT_STREAMS_API_KEY_EU_DE": "eu-key",
                            "ENVIRONMENT": "production",
                        },
                        clear=True,
                    ):
                        mock_dt.now.return_value = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
                        client = KafkaEventStreamsClient()

                        client.emit_job_started(job_us, "classical_24x120")
                        client.emit_job_started(job_eu, "classical_24x120")

        assert mock_producer_us.produce.called
        assert mock_producer_eu.produce.called

    def test_unconfigured_region_raises(self):
        job = _make_job(instance_crn="crn:v1:bluemix:public:quantum-computing:au-syd:a/abc:def::")

        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
            with patch(f"{_CLIENT_MOD}.uuid"):
                with patch(f"{_CLIENT_MOD}.datetime") as mock_dt:
                    with patch.dict(
                        os.environ,
                        {
                            "EVENT_STREAMS_BOOTSTRAP_SERVERS": "b:9093",
                            "EVENT_STREAMS_API_KEY": "k",
                            "ENVIRONMENT": "production",
                        },
                        clear=True,
                    ):
                        mock_dt.now.return_value = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
                        client = KafkaEventStreamsClient()
                        mock_producer = mock_producer_cls.return_value
                        mock_producer.flush.return_value = 0

                        with pytest.raises(RuntimeError, match="No producer configured for region au-syd"):
                            client.emit_job_started(job, "classical_24x120")

    def test_null_crn_uses_default_region(self):
        job = _make_job(instance_crn=None)

        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
            with patch(f"{_CLIENT_MOD}.uuid"):
                with patch(f"{_CLIENT_MOD}.datetime") as mock_dt:
                    with patch.dict(
                        os.environ,
                        {
                            "EVENT_STREAMS_BOOTSTRAP_SERVERS": "b:9093",
                            "EVENT_STREAMS_API_KEY": "k",
                            "ENVIRONMENT": "production",
                        },
                        clear=True,
                    ):
                        mock_dt.now.return_value = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
                        client = KafkaEventStreamsClient()
                        mock_producer = mock_producer_cls.return_value
                        mock_producer.flush.return_value = 0

                        client.emit_job_started(job, "classical_24x120")

        mock_producer.produce.assert_called_once()

    def test_malformed_crn_uses_default_region(self):
        job = _make_job(instance_crn="not:a:valid:crn")

        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
            with patch(f"{_CLIENT_MOD}.uuid"):
                with patch(f"{_CLIENT_MOD}.datetime") as mock_dt:
                    with patch.dict(
                        os.environ,
                        {
                            "EVENT_STREAMS_BOOTSTRAP_SERVERS": "b:9093",
                            "EVENT_STREAMS_API_KEY": "k",
                            "ENVIRONMENT": "production",
                        },
                        clear=True,
                    ):
                        mock_dt.now.return_value = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
                        client = KafkaEventStreamsClient()
                        mock_producer = mock_producer_cls.return_value
                        mock_producer.flush.return_value = 0

                        client.emit_job_started(job, "classical_24x120")

        mock_producer.produce.assert_called_once()

    def test_broker_list_without_matching_api_key_raises_at_init(self):
        with patch(f"{_CLIENT_MOD}.Producer"):
            with patch.dict(
                os.environ,
                {
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS": "b:9093",
                    "EVENT_STREAMS_API_KEY": "k",
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS_EU_DE": "broker-eu:9093",
                    "ENVIRONMENT": "production",
                },
                clear=True,
            ):
                with pytest.raises(ValueError, match="missing EVENT_STREAMS_API_KEY_EU_DE"):
                    KafkaEventStreamsClient()

    def test_startup_log_line(self, caplog):
        with patch(f"{_CLIENT_MOD}.Producer"):
            with patch.dict(
                os.environ,
                {
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS": "broker-us:9093",
                    "EVENT_STREAMS_API_KEY": "us-key",
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS_EU_DE": "broker-eu:9093",
                    "EVENT_STREAMS_API_KEY_EU_DE": "eu-key",
                    "ENVIRONMENT": "production",
                },
                clear=True,
            ):
                with caplog.at_level(logging.INFO):
                    KafkaEventStreamsClient()

        assert "Event Streams producers initialized" in caplog.text
        assert "regions=" in caplog.text
        assert "default=us-east" in caplog.text

    def test_region_from_crn_extracts_correctly(self):
        assert (
            KafkaEventStreamsClient._region_from_crn("crn:v1:bluemix:public:quantum-computing:us-east:a/abc:def::")
            == "us-east"
        )
        assert (
            KafkaEventStreamsClient._region_from_crn("crn:v1:bluemix:public:quantum-computing:eu-de:a/abc:def::")
            == "eu-de"
        )

    def test_region_from_crn_returns_none_for_invalid_crn(self):
        assert KafkaEventStreamsClient._region_from_crn(None) is None
        assert KafkaEventStreamsClient._region_from_crn("") is None
        assert KafkaEventStreamsClient._region_from_crn("not:a:valid:crn") is None

    def test_filler_job_publishes_nothing(self):
        """A filler job generates no usage events: the base class short-circuits all four emits."""
        job = _make_job()
        job.filler = True

        with patch(f"{_CLIENT_MOD}.Producer") as mock_producer_cls:
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
                        mock_dt.now.return_value = datetime(2026, 1, 1, 12, 0, 1, tzinfo=timezone.utc)

                        client = KafkaEventStreamsClient()
                        mock_producer = mock_producer_cls.return_value
                        mock_producer.flush.return_value = 0

                        client.emit_job_started(job)
                        client.emit_job_in_progress(job)
                        client.emit_job_completed(job)
                        client.emit_license_fee(job)

        mock_producer.produce.assert_not_called()
