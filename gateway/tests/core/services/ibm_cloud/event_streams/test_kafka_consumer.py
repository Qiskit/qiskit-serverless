"""Unit tests for KafkaRegionalConsumer: consumer setup from Django settings, the bounded,
non-blocking drain the single-threaded scheduler loop depends on, what gets committed, and how
errors are recovered from."""

import json
import logging
from unittest.mock import MagicMock, patch

import pytest
from confluent_kafka import KafkaError, KafkaException

from core.ibm_cloud.event_streams.kafka_consumer import (
    MAX_MESSAGES_PER_REGION_PER_TICK,
    DrainStats,
    InvalidEventError,
    KafkaRegionalConsumer,
)

_MOD = "core.ibm_cloud.event_streams.kafka_consumer"
_TOPICS = ["topic-a", "topic-b"]
_GROUP = "my-group"


def _never_stop() -> bool:
    """A kill signal that never arrives."""
    return False


def _configure(settings, **overrides):
    """Set the Event Streams settings the consumer reads, with sane defaults."""
    settings.ENVIRONMENT = overrides.get("environment", "staging")
    settings.EVENT_STREAMS_BOOTSTRAP_SERVERS = overrides.get("bootstrap_servers", "broker1:9093")
    settings.EVENT_STREAMS_API_KEY = overrides.get("api_key", "my-key")
    settings.EVENT_STREAMS_USER = overrides.get("user", "token")
    settings.EVENT_STREAMS_MAIN_REGION = overrides.get("main_region", "us-east")
    settings.EVENT_STREAMS_REGIONS = overrides.get("regions", {})


_EU_DE = {"eu-de": {"bootstrap_servers": "broker-eu:9093", "api_key": "eu-key", "user": "token"}}


def _message(payload=None, *, raw=None, topic="topic-a", partition=0, offset=0, key=b"acc-key"):
    """A Kafka message carrying payload (as JSON) or raw bytes, with no error."""
    msg = MagicMock()
    msg.error.return_value = None
    msg.topic.return_value = topic
    msg.partition.return_value = partition
    msg.offset.return_value = offset
    msg.key.return_value = key
    msg.value.return_value = raw if payload is None else json.dumps(payload).encode("utf-8")
    return msg


def _error_message(error: KafkaError) -> MagicMock:
    msg = MagicMock()
    msg.error.return_value = error
    return msg


def _transport_error() -> KafkaError:
    return KafkaError(KafkaError._TRANSPORT, "broker said no")  # pylint: disable=protected-access


def _fatal_error() -> KafkaError:
    return KafkaError(KafkaError._FATAL, "fenced", fatal=True)  # pylint: disable=protected-access


def _kafka(*batches):
    """A Consumer mock whose consume() returns each batch in turn, then nothing forever."""
    kafka = MagicMock()
    kafka.consume.side_effect = list(batches) + [[]] * 100
    return kafka


def _committed(kafka) -> list[tuple[str, int, int]]:
    """Every (topic, partition, offset) kafka committed, in order."""
    result = []
    for call in kafka.commit.call_args_list:
        assert call.kwargs["asynchronous"] is True
        result.extend((tp.topic, tp.partition, tp.offset) for tp in call.kwargs["offsets"])
    return result


def _consumer(handler=None) -> KafkaRegionalConsumer:
    return KafkaRegionalConsumer(topics=_TOPICS, group_id=_GROUP, handler=handler or MagicMock())


def _drain(consumer, should_stop=_never_stop) -> DrainStats:
    stats = DrainStats()
    consumer.drain(should_stop, stats)
    return stats


class TestSetup:
    """The credentials come from the settings, not from the environment directly: the suffixed
    per-region variables are discovered once at settings import time."""

    def test_consumer_configured_with_sasl_plain_tls(self, settings):
        _configure(settings, bootstrap_servers="broker1:9093", api_key="my-key")

        with patch(f"{_MOD}.Consumer") as mock_consumer_cls:
            _drain(_consumer())

        config = mock_consumer_cls.call_args[0][0]
        assert {k: v for k, v in config.items() if not callable(v)} == {
            "bootstrap.servers": "broker1:9093",
            "security.protocol": "SASL_SSL",
            "sasl.mechanisms": "PLAIN",
            "sasl.username": "token",
            "sasl.password": "my-key",
            "group.id": _GROUP,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
        assert callable(config["error_cb"])
        assert callable(config["on_commit"])

    def test_subscribes_to_the_topics(self, settings):
        _configure(settings)

        with patch(f"{_MOD}.Consumer") as mock_consumer_cls:
            _drain(_consumer())

        mock_consumer_cls.return_value.subscribe.assert_called_once_with(_TOPICS)

    def test_regional_credentials_come_from_settings(self, settings):
        _configure(
            settings,
            bootstrap_servers="broker-main:9093",
            api_key="main-key",
            user="main-user",
            regions={"eu-de": {"bootstrap_servers": "broker-eu:9093", "api_key": "eu-key", "user": "eu-user"}},
        )

        with patch(f"{_MOD}.Consumer") as mock_consumer_cls:
            _drain(_consumer())

        by_broker = {call[0][0]["bootstrap.servers"]: call[0][0] for call in mock_consumer_cls.call_args_list}
        assert len(by_broker) == 2
        assert by_broker["broker-main:9093"]["sasl.username"] == "main-user"
        assert by_broker["broker-main:9093"]["sasl.password"] == "main-key"
        assert by_broker["broker-eu:9093"]["sasl.username"] == "eu-user"
        assert by_broker["broker-eu:9093"]["sasl.password"] == "eu-key"

    def test_suffixed_region_overrides_the_main_region_entry(self, settings):
        """Same precedence KafkaProducers gives them, so the two never disagree on a region."""
        _configure(
            settings,
            main_region="us-east",
            bootstrap_servers="broker-main:9093",
            regions={"us-east": {"bootstrap_servers": "broker-override:9093", "api_key": "k", "user": "token"}},
        )

        with patch(f"{_MOD}.Consumer") as mock_consumer_cls:
            _drain(_consumer())

        mock_consumer_cls.assert_called_once()
        assert mock_consumer_cls.call_args[0][0]["bootstrap.servers"] == "broker-override:9093"

    def test_no_connection_is_opened_before_the_first_drain(self, settings):
        """Main builds every task up front, so construction must stay cheap."""
        _configure(settings)

        with patch(f"{_MOD}.Consumer") as mock_consumer_cls:
            _consumer()

        mock_consumer_cls.assert_not_called()


class TestDrain:
    """drain() runs inside the scheduler's single-threaded tick, so it must always return."""

    def test_drain_consumes_without_blocking(self, settings):
        _configure(settings)
        kafka = _kafka()

        with patch(f"{_MOD}.Consumer", return_value=kafka):
            _drain(_consumer())

        kafka.consume.assert_called_once_with(num_messages=MAX_MESSAGES_PER_REGION_PER_TICK, timeout=0)

    def test_drain_hands_each_event_to_the_handler(self, settings):
        _configure(settings)
        handler = MagicMock()
        kafka = _kafka([_message({"account_id": "acc-1"}, key=b"k1")])

        with patch(f"{_MOD}.Consumer", return_value=kafka):
            stats = _drain(_consumer(handler))

        handler.assert_called_once_with({"account_id": "acc-1"}, "k1", "us-east")
        assert stats.counts[("us-east", "handled")] == 1

    def test_drain_commits_the_next_offset_of_each_partition_asynchronously(self, settings):
        _configure(settings)
        kafka = _kafka(
            [
                _message({"n": 1}, partition=0, offset=5),
                _message({"n": 2}, partition=1, offset=9),
                _message({"n": 3}, partition=0, offset=6),
            ]
        )

        with patch(f"{_MOD}.Consumer", return_value=kafka):
            _drain(_consumer())

        kafka.commit.assert_called_once()
        assert sorted(_committed(kafka)) == [("topic-a", 0, 7), ("topic-a", 1, 10)]

    def test_drain_does_not_commit_when_nothing_was_queued(self, settings):
        _configure(settings)
        kafka = _kafka()

        with patch(f"{_MOD}.Consumer", return_value=kafka):
            _drain(_consumer())

        kafka.commit.assert_not_called()

    def test_drain_stops_mid_batch_on_kill_signal_and_commits_only_what_it_handled(self, settings):
        """A SIGTERM has to be honoured promptly, and what was not handled must not be committed."""
        _configure(settings)
        handler = MagicMock()
        kafka = _kafka([_message({"n": i}, offset=i) for i in range(10)])

        with patch(f"{_MOD}.Consumer", return_value=kafka):
            _drain(_consumer(handler), should_stop=lambda: handler.call_count >= 3)

        assert handler.call_count == 3
        assert _committed(kafka) == [("topic-a", 0, 3)]

    def test_drain_skips_every_region_once_stopped(self, settings):
        _configure(settings, regions=_EU_DE)

        with patch(f"{_MOD}.Consumer") as mock_consumer_cls:
            _drain(_consumer(), should_stop=lambda: True)

        mock_consumer_cls.assert_not_called()

    def test_drain_visits_every_configured_region(self, settings):
        _configure(settings, regions=_EU_DE)
        kafka = MagicMock()
        kafka.consume.return_value = []

        with patch(f"{_MOD}.Consumer", return_value=kafka):
            _drain(_consumer())

        assert kafka.consume.call_count == 2

    def test_consumer_is_created_once_and_reused_across_ticks(self, settings):
        _configure(settings)
        kafka = MagicMock()
        kafka.consume.return_value = []

        with patch(f"{_MOD}.Consumer", return_value=kafka) as mock_consumer_cls:
            consumer = _consumer()
            for _ in range(10):
                _drain(consumer)

        mock_consumer_cls.assert_called_once()
        kafka.subscribe.assert_called_once()


class TestPayloads:
    """A payload nobody can handle is committed over, so it cannot stall its partition forever."""

    @pytest.mark.parametrize("raw", [b"not json at all", b"\xff\xfe", b"[1, 2]", b'"a string"'])
    def test_a_payload_that_is_not_a_json_object_is_skipped_and_committed_over(self, settings, caplog, raw):
        _configure(settings)
        handler = MagicMock()
        kafka = _kafka([_message(raw=raw, offset=4), _message({"account_id": "after"}, offset=5)])

        with patch(f"{_MOD}.Consumer", return_value=kafka):
            with caplog.at_level(logging.ERROR):
                stats = _drain(_consumer(handler))

        assert "Invalid event, skipping it" in caplog.text
        handler.assert_called_once_with({"account_id": "after"}, "acc-key", "us-east")
        assert _committed(kafka) == [("topic-a", 0, 6)]
        assert stats.counts[("us-east", "invalid")] == 1

    def test_an_event_the_handler_rejects_is_committed_over(self, settings):
        _configure(settings)
        handler = MagicMock(side_effect=InvalidEventError("no account_id"))
        kafka = _kafka([_message({}, offset=0)])

        with patch(f"{_MOD}.Consumer", return_value=kafka):
            stats = _drain(_consumer(handler))

        assert _committed(kafka) == [("topic-a", 0, 1)]
        assert stats.counts[("us-east", "invalid")] == 1

    def test_a_tombstone_is_committed_without_reaching_the_handler(self, settings, caplog):
        _configure(settings)
        handler = MagicMock()
        kafka = _kafka([_message(raw=None, offset=2, key=b"acc-9")])

        with patch(f"{_MOD}.Consumer", return_value=kafka):
            with caplog.at_level(logging.INFO):
                stats = _drain(_consumer(handler))

        handler.assert_not_called()
        assert "Tombstone" in caplog.text
        assert "key=acc-9" in caplog.text
        assert _committed(kafka) == [("topic-a", 0, 3)]
        assert stats.counts[("us-east", "tombstone")] == 1

    def test_a_message_without_key_reaches_the_handler_with_none(self, settings):
        _configure(settings)
        handler = MagicMock()
        kafka = _kafka([_message({"account_id": "a"}, key=None)])

        with patch(f"{_MOD}.Consumer", return_value=kafka):
            _drain(_consumer(handler))

        handler.assert_called_once_with({"account_id": "a"}, None, "us-east")


class TestTransientFailures:
    """Any other handler failure is retried next tick: never committed over, never lost."""

    def test_the_failed_partitions_are_rewound_and_not_committed(self, settings):
        _configure(settings)
        handler = MagicMock(side_effect=[None, RuntimeError("db down"), None, None])
        kafka = _kafka(
            [
                _message({"n": 0}, partition=0, offset=10),
                _message({"n": 1}, partition=0, offset=11),  # fails
                _message({"n": 2}, partition=1, offset=20),  # never handled
                _message({"n": 3}, partition=0, offset=12),  # never handled
            ]
        )

        with patch(f"{_MOD}.Consumer", return_value=kafka):
            stats = DrainStats()
            with pytest.raises(RuntimeError, match="db down"):
                _consumer(handler).drain(_never_stop, stats)

        assert handler.call_count == 2
        assert _committed(kafka) == [("topic-a", 0, 11)]
        rewound = sorted((c[0][0].topic, c[0][0].partition, c[0][0].offset) for c in kafka.seek.call_args_list)
        assert rewound == [("topic-a", 0, 11), ("topic-a", 1, 20)]
        assert stats.counts[("us-east", "retry")] == 1

    def test_the_other_regions_are_drained_before_the_failure_is_raised(self, settings):
        _configure(settings, bootstrap_servers="broker-main:9093", regions=_EU_DE)
        main = _kafka([_message({"region": "main"})])
        eu = _kafka([_message({"region": "eu"})])

        def handler(payload, key, region):  # pylint: disable=unused-argument
            if region == "us-east":
                raise RuntimeError("db down")

        def consumer_for(config):
            return main if "broker-main" in config["bootstrap.servers"] else eu

        with patch(f"{_MOD}.Consumer", side_effect=consumer_for):
            with pytest.raises(RuntimeError, match="db down"):
                _drain(_consumer(handler))

        assert _committed(eu) == [("topic-a", 0, 1)]
        main.commit.assert_not_called()

    def test_a_rewind_that_fails_is_logged_and_the_failure_still_raised(self, settings, caplog):
        _configure(settings)
        kafka = _kafka([_message({"n": 0})])
        kafka.seek.side_effect = KafkaException(KafkaError(KafkaError._STATE))  # pylint: disable=protected-access

        with patch(f"{_MOD}.Consumer", return_value=kafka):
            with caplog.at_level(logging.WARNING):
                with pytest.raises(RuntimeError):
                    _drain(_consumer(MagicMock(side_effect=RuntimeError("boom"))))

        assert "Could not rewind" in caplog.text

    def test_a_transient_failure_does_not_rebuild_the_consumer(self, settings):
        _configure(settings)
        kafka = _kafka([_message({"n": 0})])

        with patch(f"{_MOD}.Consumer", return_value=kafka) as mock_consumer_cls:
            consumer = _consumer(MagicMock(side_effect=[RuntimeError("boom"), None]))
            with pytest.raises(RuntimeError):
                _drain(consumer)
            _drain(consumer)

        mock_consumer_cls.assert_called_once()
        kafka.close.assert_not_called()


class TestConsumerErrors:
    """librdkafka recovers from everything but a fatal error, so only those rebuild the consumer."""

    def test_a_non_fatal_message_error_does_not_stop_the_batch(self, settings, caplog):
        _configure(settings)
        handler = MagicMock()
        kafka = _kafka([_error_message(_transport_error()), _message({"account_id": "a"})])

        with patch(f"{_MOD}.Consumer", return_value=kafka) as mock_consumer_cls:
            consumer = _consumer(handler)
            with caplog.at_level(logging.WARNING):
                stats = _drain(consumer)
            _drain(consumer)

        handler.assert_called_once()
        assert "broker said no" in caplog.text
        assert stats.counts[("us-east", "consumer_error")] == 1
        mock_consumer_cls.assert_called_once()

    def test_a_fatal_message_error_rebuilds_the_consumer_next_tick(self, settings):
        _configure(settings)
        handler = MagicMock()
        broken = _kafka([_error_message(_fatal_error()), _message({"account_id": "a"})])
        healthy = _kafka()

        with patch(f"{_MOD}.Consumer", side_effect=[broken, healthy]):
            consumer = _consumer(handler)
            stats = _drain(consumer)
            broken.close.assert_not_called()
            _drain(consumer)

        handler.assert_not_called()
        assert stats.counts[("us-east", "fatal")] == 1
        broken.close.assert_called_once()
        healthy.consume.assert_called_once()

    def test_a_fatal_error_cb_rebuilds_the_consumer_next_tick(self, settings):
        _configure(settings)
        broken = _kafka()
        healthy = _kafka()

        with patch(f"{_MOD}.Consumer", side_effect=[broken, healthy]) as mock_consumer_cls:
            consumer = _consumer()
            _drain(consumer)
            error_cb = mock_consumer_cls.call_args_list[0][0][0]["error_cb"]
            error_cb(_fatal_error())
            _drain(consumer)

        broken.close.assert_called_once()
        healthy.consume.assert_called_once()

    def test_a_non_fatal_error_cb_keeps_the_consumer(self, settings):
        _configure(settings)
        kafka = _kafka()

        with patch(f"{_MOD}.Consumer", return_value=kafka) as mock_consumer_cls:
            consumer = _consumer()
            _drain(consumer)
            mock_consumer_cls.call_args[0][0]["error_cb"](_transport_error())
            _drain(consumer)

        mock_consumer_cls.assert_called_once()

    def test_a_non_fatal_consume_exception_keeps_the_consumer(self, settings):
        _configure(settings)
        kafka = MagicMock()
        kafka.consume.side_effect = [KafkaException(_transport_error()), []]

        with patch(f"{_MOD}.Consumer", return_value=kafka) as mock_consumer_cls:
            consumer = _consumer()
            stats = _drain(consumer)
            _drain(consumer)

        mock_consumer_cls.assert_called_once()
        assert stats.counts[("us-east", "consumer_error")] == 1

    def test_a_fatal_consume_exception_rebuilds_the_consumer(self, settings):
        _configure(settings)
        broken = MagicMock()
        broken.consume.side_effect = KafkaException(_fatal_error())
        healthy = _kafka()

        with patch(f"{_MOD}.Consumer", side_effect=[broken, healthy]):
            consumer = _consumer()
            _drain(consumer)
            _drain(consumer)

        broken.close.assert_called_once()
        healthy.consume.assert_called_once()

    def test_a_failed_async_commit_is_counted_and_keeps_the_consumer(self, settings, caplog):
        _configure(settings)
        kafka = _kafka()

        with patch(f"{_MOD}.Consumer", return_value=kafka) as mock_consumer_cls:
            consumer = _consumer()
            _drain(consumer)
            on_commit = mock_consumer_cls.call_args[0][0]["on_commit"]
            stats = DrainStats()

            def consume_serving_the_callback(**_kwargs):
                on_commit(KafkaError(KafkaError.REBALANCE_IN_PROGRESS), [])
                return []

            kafka.consume.side_effect = consume_serving_the_callback
            with caplog.at_level(logging.WARNING):
                consumer.drain(_never_stop, stats)

        assert stats.counts[("us-east", "commit_error")] == 1
        assert "Commit failed" in caplog.text
        mock_consumer_cls.assert_called_once()

    def test_a_successful_async_commit_is_not_counted(self, settings):
        _configure(settings)
        kafka = _kafka()

        with patch(f"{_MOD}.Consumer", return_value=kafka) as mock_consumer_cls:
            consumer = _consumer()
            _drain(consumer)
            on_commit = mock_consumer_cls.call_args[0][0]["on_commit"]
            stats = DrainStats()

            def consume_serving_the_callback(**_kwargs):
                on_commit(None, [MagicMock(error=None)])
                return []

            kafka.consume.side_effect = consume_serving_the_callback
            consumer.drain(_never_stop, stats)

        assert not stats.counts

    def test_a_commit_that_raises_is_counted(self, settings):
        _configure(settings)
        kafka = _kafka([_message({"n": 0})])
        kafka.commit.side_effect = KafkaException(KafkaError(KafkaError._STATE))  # pylint: disable=protected-access

        with patch(f"{_MOD}.Consumer", return_value=kafka):
            stats = _drain(_consumer())

        assert stats.counts[("us-east", "commit_error")] == 1

    def test_a_consumer_that_cannot_be_built_logs_its_traceback_once_per_streak(self, settings, caplog):
        _configure(settings)

        with patch(f"{_MOD}.Consumer", side_effect=KafkaException("bad config")) as mock_consumer_cls:
            consumer = _consumer()
            with caplog.at_level(logging.ERROR):
                stats = _drain(consumer)
                _drain(consumer)
                _drain(consumer)

        assert mock_consumer_cls.call_count == 3
        with_traceback = [r for r in caplog.records if "Could not create consumer" in r.message and r.exc_info]
        assert len(with_traceback) == 1
        assert stats.counts[("us-east", "consumer_error")] == 1

    def test_a_consumer_whose_subscribe_fails_is_closed(self, settings):
        _configure(settings)
        half_built = MagicMock()
        half_built.subscribe.side_effect = KafkaException("no such topic")

        with patch(f"{_MOD}.Consumer", return_value=half_built):
            _drain(_consumer())

        half_built.close.assert_called_once()

    def test_one_failing_region_does_not_stop_the_others(self, settings):
        _configure(settings, bootstrap_servers="broker-main:9093", regions=_EU_DE)
        healthy = _kafka()

        def consumer_for(config):
            if "broker-main" in config["bootstrap.servers"]:
                raise KafkaException("bad config")
            return healthy

        with patch(f"{_MOD}.Consumer", side_effect=consumer_for):
            _drain(_consumer())

        healthy.consume.assert_called_once()


class TestClose:
    def test_close_closes_every_region_even_if_one_fails(self, settings):
        _configure(settings, bootstrap_servers="broker-main:9093", regions=_EU_DE)
        main = _kafka()
        main.close.side_effect = RuntimeError("close failed")
        eu = _kafka()

        def consumer_for(config):
            return main if "broker-main" in config["bootstrap.servers"] else eu

        with patch(f"{_MOD}.Consumer", side_effect=consumer_for):
            consumer = _consumer()
            _drain(consumer)
            consumer.close()

        main.close.assert_called_once()
        eu.close.assert_called_once()

    def test_close_before_any_drain_is_a_noop(self, settings):
        _configure(settings)

        with patch(f"{_MOD}.Consumer") as mock_consumer_cls:
            _consumer().close()

        mock_consumer_cls.assert_not_called()
