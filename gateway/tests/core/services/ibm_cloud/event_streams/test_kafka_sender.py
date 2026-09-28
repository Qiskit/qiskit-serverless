"""Unit tests for KafkaSender and NoOpSender. Neither knows about Job: they take a plain
payload dict, so tests build one directly instead of constructing a job."""

import json
import logging
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from core.ibm_cloud.event_streams.kafka_producers import UnroutableRegionError
from core.ibm_cloud.event_streams.kafka_sender import build_kafka_sender, KafkaSender, NoOpSender


def _payload(instance_crn="crn:v1:bluemix:public:quantum-computing:us-east:a/acct:inst::"):
    return {
        "specversion": "1.0",
        "id": "evt-1",
        "source": "qiskit-serverless/scheduler/fleets",
        "subject": "job-1",
        "datacontenttype": "application/json",
        "data": {"metric_type": "license_ibm-dev_fn_m", "metric_value": 1, "instance_crn": instance_crn},
    }


class TestKafkaSender:
    def test_adds_type_from_the_shared_topic_and_publishes(self):
        producer = MagicMock()
        producer.flush.return_value = 0
        producers = MagicMock()
        producers.topic = "quantum.staging.function-usage.v1"
        producers.get.return_value = producer

        sender = KafkaSender(producers)
        sender.send(_payload())

        producers.get.assert_called_once_with(_payload()["data"]["instance_crn"])
        call_kwargs = producer.produce.call_args.kwargs
        assert call_kwargs["topic"] == "quantum.staging.function-usage.v1"
        assert call_kwargs["key"] == b"job-1"  # the payload's own "subject", encoded
        sent_value = json.loads(call_kwargs["value"])
        assert sent_value["type"] == "quantum.staging.function-usage.v1"
        assert sent_value["id"] == "evt-1"  # unchanged: send never rebuilds the message

    def test_does_not_mutate_the_caller_s_payload(self):
        producer = MagicMock()
        producer.flush.return_value = 0
        producers = MagicMock()
        producers.topic = "t"
        producers.get.return_value = producer

        sender = KafkaSender(producers)
        payload = _payload()
        sender.send(payload)

        assert "type" not in payload

    def test_raises_unroutable_when_producers_cannot_route(self):
        producers = MagicMock()
        producers.get.side_effect = UnroutableRegionError("no region")

        sender = KafkaSender(producers)

        with pytest.raises(UnroutableRegionError):
            sender.send(_payload())

    def test_raises_runtime_error_when_flush_times_out(self):
        producer = MagicMock()
        producer.flush.return_value = 1
        producers = MagicMock()
        producers.topic = "t"
        producers.get.return_value = producer

        sender = KafkaSender(producers)

        with pytest.raises(RuntimeError):
            sender.send(_payload())

    def test_produce_failure_raises_plain_runtime_error_not_unroutable(self):
        """A producer.produce()/flush() failure is a transient Kafka outage, not a routing or
        config gap: it must stay a plain RuntimeError so it keeps tripping the caller's circuit
        breaker."""
        producer = MagicMock()
        producer.produce.side_effect = Exception("broker unreachable")
        producers = MagicMock()
        producers.topic = "t"
        producers.get.return_value = producer

        sender = KafkaSender(producers)

        with pytest.raises(RuntimeError) as exc_info:
            sender.send(_payload())
        assert not isinstance(exc_info.value, UnroutableRegionError)

    def test_missing_instance_crn_is_unroutable_not_a_key_error(self):
        """A malformed payload must not crash the caller's drain loop with a bare KeyError."""
        producers = MagicMock()
        producers.get.side_effect = UnroutableRegionError("cannot determine region")

        sender = KafkaSender(producers)
        payload = {"subject": "job-1", "data": {}}

        with pytest.raises(UnroutableRegionError):
            sender.send(payload)
        producers.get.assert_called_once_with(None)

    def test_explicit_none_data_is_unroutable_not_an_attribute_error(self):
        """Same defense as the missing-key case, for a payload where "data" is present but None."""
        producers = MagicMock()
        producers.get.side_effect = UnroutableRegionError("cannot determine region")

        sender = KafkaSender(producers)
        payload = {"subject": "job-1", "data": None}

        with pytest.raises(UnroutableRegionError):
            sender.send(payload)
        producers.get.assert_called_once_with(None)


class TestNoOpSender:
    def test_logs_instead_of_sending(self, caplog):
        sender = NoOpSender()
        with caplog.at_level(logging.INFO):
            sender.send(_payload())
        assert "noop" in caplog.text


class TestBuildKafkaSender:
    @override_settings(EVENT_STREAMS_ENABLED=False)
    def test_builds_a_noop_sender_when_event_streams_is_disabled(self):
        assert isinstance(build_kafka_sender(), NoOpSender)

    @override_settings(EVENT_STREAMS_ENABLED=True)
    def test_builds_a_kafka_sender_when_event_streams_is_enabled(self):
        with patch("core.ibm_cloud.event_streams.kafka_sender.KafkaSender") as mock_kafka_sender:
            result = build_kafka_sender()

        mock_kafka_sender.assert_called_once_with()
        assert result is mock_kafka_sender.return_value
