"""Unit tests for KafkaSender and NoOpSender. Neither knows about Job: they take a plain
payload dict, so tests build one directly instead of constructing a job."""

import json
import logging
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from core.ibm_cloud.event_streams.kafka_producers import UnroutableRegionError
from core.ibm_cloud.event_streams.kafka_sender import build_kafka_sender, KafkaSender, NoOpSender
from core.ibm_cloud.sender import PendingMessage


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

    def test_raises_plain_runtime_error_when_delivery_callback_reports_error(self):
        """flush() returning 0 only means nothing is left outstanding, not that delivery succeeded: a
        fast broker-side rejection (e.g. a topic ACL problem) invokes the delivery callback with an
        error before flush() returns 0. send must still raise, as a plain RuntimeError."""
        producer = MagicMock()
        producer.flush.return_value = 0
        producer.produce.side_effect = lambda **kwargs: kwargs["callback"](
            Exception("Topic authorization failed"), None
        )
        producers = MagicMock()
        producers.topic = "t"
        producers.get.return_value = producer

        sender = KafkaSender(producers)

        with pytest.raises(RuntimeError, match="message delivery failed") as exc_info:
            sender.send(_payload())
        assert not isinstance(exc_info.value, UnroutableRegionError)

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


class _FakeProducer:
    """Like confluent's Producer, delivery callbacks only run inside flush(). Keys in `reject` get an
    error, keys in `hang` are left outstanding (their callback is kept in `late`)."""

    def __init__(self, reject=(), hang=()):
        self.reject, self.hang = set(reject), set(hang)
        self.queued, self.late, self.flush_timeouts = [], [], []

    def produce(self, **kwargs):
        self.queued.append(kwargs)

    def flush(self, timeout):
        self.flush_timeouts.append(timeout)
        for kwargs in self.queued:
            if kwargs["key"] in self.hang:
                self.late.append(kwargs["callback"])
            elif kwargs["key"] in self.reject:
                kwargs["callback"](Exception("Topic authorization failed"), None)
            else:
                kwargs["callback"](None, None)
        remaining = sum(1 for kwargs in self.queued if kwargs["key"] in self.hang)
        self.queued = []
        return remaining


def _payload_for(subject, crn=None):
    payload = {**_payload(), "subject": subject}
    if crn:
        payload["data"] = {**payload["data"], "instance_crn": crn}
    return payload


class TestKafkaSenderBatch:
    @staticmethod
    def _producers(producer, topic="t"):
        producers = MagicMock()
        producers.topic = topic
        producers.get.return_value = producer
        return producers

    def test_flushes_once_and_returns_only_the_keys_the_broker_confirmed(self):
        producer = _FakeProducer(reject={b"job-2"})
        sender = KafkaSender(self._producers(producer))

        delivered = sender.send_batch(
            [PendingMessage(1, _payload_for("job-1")), PendingMessage(2, _payload_for("job-2"))]
        )

        assert delivered == {1}
        assert len(producer.flush_timeouts) == 1

    def test_the_flush_uses_the_given_timeout(self):
        producer = _FakeProducer()
        sender = KafkaSender(self._producers(producer))

        sender.send_batch([PendingMessage(1, _payload_for("job-1"))], timeout=1.5)

        assert producer.flush_timeouts == [1.5]

    def test_a_payload_that_cannot_be_routed_is_left_out_and_the_rest_are_sent(self):
        producer = _FakeProducer()
        producers = self._producers(producer)
        producers.get.side_effect = [UnroutableRegionError("no region"), producer]
        sender = KafkaSender(producers)

        delivered = sender.send_batch(
            [PendingMessage(1, _payload_for("job-1")), PendingMessage(2, _payload_for("job-2"))]
        )

        assert delivered == {2}

    def test_a_message_still_outstanding_after_the_flush_timeout_is_left_out(self):
        producer = _FakeProducer(hang={b"job-1"})
        sender = KafkaSender(self._producers(producer))

        assert sender.send_batch(
            [PendingMessage(1, _payload_for("job-1")), PendingMessage(2, _payload_for("job-2"))]
        ) == {2}

    def test_a_callback_that_fires_after_the_flush_does_not_change_the_result(self):
        producer = _FakeProducer(hang={b"job-1"})
        sender = KafkaSender(self._producers(producer))

        delivered = sender.send_batch([PendingMessage(1, _payload_for("job-1"))])
        producer.late[0](None, None)  # the broker acks it during a later flush

        assert delivered == set()

    def test_one_region_timing_out_does_not_hide_the_other_region_s_confirmations(self):
        healthy, dead = _FakeProducer(), _FakeProducer(hang={b"job-2"})
        producers = self._producers(None)
        producers.get.side_effect = lambda crn: healthy if "us-east" in crn else dead
        sender = KafkaSender(producers)

        delivered = sender.send_batch(
            [
                PendingMessage(
                    1, _payload_for("job-1", "crn:v1:bluemix:public:quantum-computing:us-east:a/acct:inst::")
                ),
                PendingMessage(2, _payload_for("job-2", "crn:v1:bluemix:public:quantum-computing:eu-de:a/acct:inst::")),
            ]
        )

        assert delivered == {1}
        assert len(healthy.flush_timeouts) == 1
        assert len(dead.flush_timeouts) == 1

    def test_does_not_mutate_the_callers_payload(self):
        sender = KafkaSender(self._producers(_FakeProducer()))
        payload = _payload()

        sender.send_batch([PendingMessage(1, payload)])

        assert "type" not in payload


class TestKafkaSenderMalformedPayloads:
    def test_send_batch_never_raises_on_a_payload_that_is_not_a_dict_and_still_sends_the_rest(self):
        producer = _FakeProducer()
        producers = MagicMock()
        producers.topic = "t"
        producers.get.return_value = producer
        sender = KafkaSender(producers)

        delivered = sender.send_batch([PendingMessage(1, [1, 2]), PendingMessage(2, _payload_for("job-2"))])

        assert delivered == {2}


class TestKafkaSenderWithoutWaiting:
    @staticmethod
    def _sender(producer):
        producers = MagicMock(topic="t")
        producers.get.return_value = producer
        return KafkaSender(producers=producers)

    def test_timeout_zero_produces_and_polls_without_flushing(self):
        producer = MagicMock()

        self._sender(producer).send(_payload(), timeout=0)

        producer.produce.assert_called_once()
        producer.poll.assert_called_once_with(0)
        producer.flush.assert_not_called()

    def test_a_message_that_cannot_be_queued_is_dropped_with_a_warning_and_does_not_raise(self, caplog):
        producer = MagicMock()
        producer.produce.side_effect = BufferError("queue full")

        with caplog.at_level(logging.WARNING):
            self._sender(producer).send(_payload(), timeout=0)

        assert "queue full" in caplog.text
        assert "job-1" in caplog.text

    def test_a_payload_that_is_not_a_dict_is_dropped_and_does_not_raise(self, caplog):
        with caplog.at_level(logging.WARNING):
            self._sender(MagicMock()).send("not a dict", timeout=0)

        assert "1 best effort message(s) dropped" in caplog.text

    def test_a_failed_delivery_is_dropped_with_a_warning_that_names_the_message(self, caplog):
        producer = MagicMock()
        self._sender(producer).send(_payload(), timeout=0)

        with caplog.at_level(logging.WARNING):
            producer.produce.call_args.kwargs["callback"](Exception("Topic authorization failed"), None)

        assert "Topic authorization failed" in caplog.text
        assert "job-1" in caplog.text

    def test_a_successful_delivery_logs_nothing(self, caplog):
        producer = MagicMock()
        self._sender(producer).send(_payload(), timeout=0)

        with caplog.at_level(logging.WARNING):
            producer.produce.call_args.kwargs["callback"](None, None)

        assert caplog.text == ""

    def test_many_drops_are_reported_as_one_warning_per_interval(self, caplog):
        producer = MagicMock()
        producer.produce.side_effect = BufferError("queue full")
        sender = self._sender(producer)

        with patch("core.ibm_cloud.event_streams.kafka_sender.time.monotonic", side_effect=[0, 1, 2, 31]):
            with caplog.at_level(logging.WARNING):
                for _ in range(4):
                    sender.send(_payload(), timeout=0)

        reports = [record.getMessage() for record in caplog.records]
        assert len(reports) == 2
        assert reports[0].startswith("1 best effort message(s) dropped")
        assert reports[1].startswith("3 best effort message(s) dropped")


class TestSenderDefaultSendBatch:
    def test_swallows_and_logs_a_failure_and_still_sends_the_rest(self, caplog):
        sender = NoOpSender()
        with patch.object(NoOpSender, "send", side_effect=[None, RuntimeError("boom"), None]):
            with caplog.at_level(logging.ERROR):
                delivered = sender.send_batch([PendingMessage(1, {}), PendingMessage(2, {}), PendingMessage(3, {})])

        assert delivered == {1, 3}
        assert "boom" in caplog.text


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
