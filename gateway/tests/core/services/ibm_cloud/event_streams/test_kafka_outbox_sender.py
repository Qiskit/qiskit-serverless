"""Unit tests for KafkaOutboxSender and NoOpOutboxSender."""

import json
import logging
from unittest.mock import MagicMock

import pytest

from core.ibm_cloud.event_streams.kafka_outbox_sender import KafkaOutboxSender, NoOpOutboxSender
from core.ibm_cloud.event_streams.kafka_producers import UnroutableRegionError


def _payload(instance_crn="crn:v1:bluemix:public:quantum-computing:us-east:a/acct:inst::"):
    return {
        "specversion": "1.0",
        "id": "evt-1",
        "source": "qiskit-serverless/scheduler/fleets",
        "subject": "job-1",
        "datacontenttype": "application/json",
        "data": {"metric_type": "license_ibm-dev_fn_m", "metric_value": 1, "instance_crn": instance_crn},
    }


class TestKafkaOutboxSender:
    def test_adds_type_from_the_shared_topic_and_publishes(self):
        producer = MagicMock()
        producer.flush.return_value = 0
        producers = MagicMock()
        producers.topic = "quantum.staging.function-usage.v1"
        producers.get.return_value = producer

        sender = KafkaOutboxSender(producers)
        sender.send(_payload())

        producers.get.assert_called_once_with(_payload()["data"]["instance_crn"])
        sent_value = json.loads(producer.produce.call_args.kwargs["value"])
        assert sent_value["type"] == "quantum.staging.function-usage.v1"
        assert sent_value["id"] == "evt-1"  # unchanged: send never rebuilds the message

    def test_raises_unroutable_when_producers_cannot_route(self):
        producers = MagicMock()
        producers.get.side_effect = UnroutableRegionError("no region")

        sender = KafkaOutboxSender(producers)

        with pytest.raises(UnroutableRegionError):
            sender.send(_payload())

    def test_raises_runtime_error_when_flush_times_out(self):
        producer = MagicMock()
        producer.flush.return_value = 1
        producers = MagicMock()
        producers.topic = "t"
        producers.get.return_value = producer

        sender = KafkaOutboxSender(producers)

        with pytest.raises(RuntimeError):
            sender.send(_payload())


class TestNoOpOutboxSender:
    def test_logs_instead_of_sending(self, caplog):
        sender = NoOpOutboxSender()
        with caplog.at_level(logging.INFO):
            sender.send(_payload())
        assert "noop" in caplog.text
