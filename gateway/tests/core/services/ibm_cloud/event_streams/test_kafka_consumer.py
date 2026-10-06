"""Unit tests for KafkaBlockedAccountsConsumer: consumer/topic setup from Django settings, and
the bounded, non-blocking drain the single-threaded scheduler loop depends on."""

import json
import logging
from unittest.mock import MagicMock, patch

from core.ibm_cloud.event_streams.kafka_consumer import (
    MAX_MESSAGES_PER_REGION_PER_TICK,
    KafkaBlockedAccountsConsumer,
)

_MOD = "core.ibm_cloud.event_streams.kafka_consumer"


def _never_stop() -> bool:
    """A kill signal that never arrives."""
    return False


def _configure(settings, **overrides):
    """Set the Event Streams settings KafkaBlockedAccountsConsumer reads, with sane defaults."""
    settings.ENVIRONMENT = overrides.get("environment", "staging")
    settings.EVENT_STREAMS_BOOTSTRAP_SERVERS = overrides.get("bootstrap_servers", "broker1:9093")
    settings.EVENT_STREAMS_API_KEY = overrides.get("api_key", "my-key")
    settings.EVENT_STREAMS_USER = overrides.get("user", "token")
    settings.EVENT_STREAMS_MAIN_REGION = overrides.get("main_region", "us-east")
    settings.EVENT_STREAMS_REGIONS = overrides.get("regions", {})


def _message(payload: dict) -> MagicMock:
    """A Kafka message carrying payload, with no error."""
    msg = MagicMock()
    msg.error.return_value = None
    msg.value.return_value = json.dumps(payload).encode("utf-8")
    return msg


def _messages_then_empty(*payloads):
    """poll() side effect: each payload in turn, then None forever (an empty local queue)."""
    return [_message(payload) for payload in payloads] + [None] * 1000


class TestKafkaBlockedAccountsConsumerSetup:
    """The credentials come from the settings, not from the environment directly: the suffixed
    per-region variables are discovered once at settings import time."""

    def test_consumer_configured_with_sasl_plain_tls(self, settings):
        _configure(settings, bootstrap_servers="broker1:9093", api_key="my-key", environment="staging")

        with patch(f"{_MOD}.Consumer") as mock_consumer_cls:
            consumer = KafkaBlockedAccountsConsumer()
            consumer.drain(_never_stop)

        mock_consumer_cls.assert_called_once_with(
            {
                "bootstrap.servers": "broker1:9093",
                "security.protocol": "SASL_SSL",
                "sasl.mechanisms": "PLAIN",
                "sasl.username": "token",
                "sasl.password": "my-key",
                "group.id": "qiskit-serverless-scheduler-blocked-accounts-staging",
                "enable.auto.commit": False,
                "auto.offset.reset": "earliest",
            }
        )

    def test_topics_constructed_from_environment(self, settings):
        _configure(settings, environment="staging")

        with patch(f"{_MOD}.Consumer"):
            consumer = KafkaBlockedAccountsConsumer()

        assert consumer.blocked_accounts_topics == [
            "quantum.staging.blocked-account-plans.v1",
            "quantum.staging.blocked-account-plans-non-quantum.v1",
        ]

    def test_subscribes_to_both_topics(self, settings):
        _configure(settings, environment="production")

        with patch(f"{_MOD}.Consumer") as mock_consumer_cls:
            consumer = KafkaBlockedAccountsConsumer()
            consumer.drain(_never_stop)

        mock_consumer_cls.return_value.subscribe.assert_called_once_with(
            [
                "quantum.production.blocked-account-plans.v1",
                "quantum.production.blocked-account-plans-non-quantum.v1",
            ]
        )

    def test_regional_credentials_come_from_settings(self, settings):
        _configure(
            settings,
            bootstrap_servers="broker-main:9093",
            api_key="main-key",
            user="main-user",
            regions={"eu-de": {"bootstrap_servers": "broker-eu:9093", "api_key": "eu-key", "user": "eu-user"}},
        )

        with patch(f"{_MOD}.Consumer") as mock_consumer_cls:
            consumer = KafkaBlockedAccountsConsumer()
            consumer.drain(_never_stop)

        configs = [call[0][0] for call in mock_consumer_cls.call_args_list]
        assert len(configs) == 2
        by_broker = {config["bootstrap.servers"]: config for config in configs}
        assert by_broker["broker-main:9093"]["sasl.username"] == "main-user"
        assert by_broker["broker-main:9093"]["sasl.password"] == "main-key"
        assert by_broker["broker-eu:9093"]["sasl.username"] == "eu-user"
        assert by_broker["broker-eu:9093"]["sasl.password"] == "eu-key"

    def test_event_streams_main_region_respected(self, settings):
        _configure(settings, main_region="eu-gb")

        with patch(f"{_MOD}.Consumer"):
            consumer = KafkaBlockedAccountsConsumer()

        assert list(consumer._region_configs) == ["eu-gb"]

    def test_suffixed_region_overrides_the_main_region_entry(self, settings):
        """Same precedence KafkaProducers gives them, so the two never disagree on a region."""
        _configure(
            settings,
            main_region="us-east",
            bootstrap_servers="broker-main:9093",
            regions={"us-east": {"bootstrap_servers": "broker-override:9093", "api_key": "k", "user": "token"}},
        )

        with patch(f"{_MOD}.Consumer") as mock_consumer_cls:
            consumer = KafkaBlockedAccountsConsumer()
            consumer.drain(_never_stop)

        assert list(consumer._region_configs) == ["us-east"]
        mock_consumer_cls.assert_called_once()
        assert mock_consumer_cls.call_args[0][0]["bootstrap.servers"] == "broker-override:9093"

    def test_no_connection_is_opened_before_the_first_drain(self, settings):
        """Main builds every task up front, so construction must stay cheap."""
        _configure(settings)

        with patch(f"{_MOD}.Consumer") as mock_consumer_cls:
            KafkaBlockedAccountsConsumer()

        mock_consumer_cls.assert_not_called()


class TestKafkaBlockedAccountsConsumerDrain:
    """drain() runs inside the scheduler's single-threaded tick, so it must always return."""

    def test_drain_polls_without_blocking(self, settings):
        _configure(settings)

        with patch(f"{_MOD}.Consumer") as mock_consumer_cls:
            mock_consumer_cls.return_value.poll.return_value = None
            consumer = KafkaBlockedAccountsConsumer()
            consumer.drain(_never_stop)

        mock_consumer_cls.return_value.poll.assert_called_once_with(timeout=0)

    def test_drain_handles_and_commits_queued_messages(self, settings, caplog):
        _configure(settings)
        kafka = MagicMock()
        kafka.poll.side_effect = _messages_then_empty(
            {"account_id": "acc-1", "plan_id": "plan-1", "subscription_id": "sub-1", "deleted": True}
        )

        with patch(f"{_MOD}.Consumer", return_value=kafka):
            consumer = KafkaBlockedAccountsConsumer()
            with caplog.at_level(logging.INFO):
                consumer.drain(_never_stop)

        assert "account_id=acc-1" in caplog.text
        assert "plan_id=plan-1" in caplog.text
        assert "subscription_id=sub-1" in caplog.text
        assert "deleted=True" in caplog.text
        kafka.commit.assert_called_once_with(asynchronous=False)

    def test_drain_commits_once_per_batch(self, settings):
        _configure(settings)
        kafka = MagicMock()
        kafka.poll.side_effect = _messages_then_empty({"account_id": "a"}, {"account_id": "b"}, {"account_id": "c"})

        with patch(f"{_MOD}.Consumer", return_value=kafka):
            consumer = KafkaBlockedAccountsConsumer()
            consumer.drain(_never_stop)

        kafka.commit.assert_called_once_with(asynchronous=False)

    def test_drain_does_not_commit_when_nothing_was_queued(self, settings):
        _configure(settings)
        kafka = MagicMock()
        kafka.poll.return_value = None

        with patch(f"{_MOD}.Consumer", return_value=kafka):
            consumer = KafkaBlockedAccountsConsumer()
            consumer.drain(_never_stop)

        kafka.commit.assert_not_called()

    def test_drain_is_bounded_so_a_backlog_cannot_hold_the_tick(self, settings):
        """An endless supply of messages must not turn the drain into an endless loop: the rest
        of the backlog waits for the next tick."""
        _configure(settings)
        kafka = MagicMock()
        kafka.poll.return_value = _message({"account_id": "acc"})

        with patch(f"{_MOD}.Consumer", return_value=kafka):
            consumer = KafkaBlockedAccountsConsumer()
            consumer.drain(_never_stop)

        assert kafka.poll.call_count == MAX_MESSAGES_PER_REGION_PER_TICK

    def test_drain_stops_mid_batch_on_kill_signal(self, settings):
        """A SIGTERM has to be honoured promptly, without waiting out the whole batch."""
        _configure(settings)
        kafka = MagicMock()
        polls = 0

        def should_stop():
            return polls >= 3

        def poll(timeout):  # pylint: disable=unused-argument
            nonlocal polls
            polls += 1
            return _message({"account_id": "acc"})

        kafka.poll.side_effect = poll

        with patch(f"{_MOD}.Consumer", return_value=kafka):
            consumer = KafkaBlockedAccountsConsumer()
            consumer.drain(should_stop)

        assert polls == 3

    def test_drain_skips_every_region_once_stopped(self, settings):
        _configure(
            settings,
            regions={"eu-de": {"bootstrap_servers": "broker-eu:9093", "api_key": "eu-key", "user": "token"}},
        )

        with patch(f"{_MOD}.Consumer") as mock_consumer_cls:
            consumer = KafkaBlockedAccountsConsumer()
            consumer.drain(lambda: True)

        mock_consumer_cls.assert_not_called()

    def test_drain_visits_every_configured_region(self, settings):
        _configure(
            settings,
            regions={"eu-de": {"bootstrap_servers": "broker-eu:9093", "api_key": "eu-key", "user": "token"}},
        )
        kafka = MagicMock()
        kafka.poll.return_value = None

        with patch(f"{_MOD}.Consumer", return_value=kafka):
            consumer = KafkaBlockedAccountsConsumer()
            consumer.drain(_never_stop)

        assert kafka.poll.call_count == 2

    def test_message_error_ends_the_region_for_this_tick(self, settings, caplog):
        _configure(settings)
        kafka = MagicMock()
        failed = MagicMock()
        failed.error.return_value = "broker said no"
        kafka.poll.return_value = failed

        with patch(f"{_MOD}.Consumer", return_value=kafka):
            consumer = KafkaBlockedAccountsConsumer()
            with caplog.at_level(logging.ERROR):
                consumer.drain(_never_stop)

        assert kafka.poll.call_count == 1
        assert "broker said no" in caplog.text
        kafka.commit.assert_not_called()


class TestKafkaBlockedAccountsConsumerReuse:
    """What keeps the per-tick drain from piling up consumers over the regions."""

    def test_consumer_is_created_once_and_reused_across_ticks(self, settings):
        _configure(settings)
        kafka = MagicMock()
        kafka.poll.return_value = None

        with patch(f"{_MOD}.Consumer", return_value=kafka) as mock_consumer_cls:
            consumer = KafkaBlockedAccountsConsumer()
            for _ in range(10):
                consumer.drain(_never_stop)

        mock_consumer_cls.assert_called_once()
        kafka.subscribe.assert_called_once()

    def test_a_failing_consumer_is_closed_before_being_replaced(self, settings, caplog):
        """Dropping it without closing would leave a zombie group member holding the partitions
        the replacement needs."""
        _configure(settings)
        broken = MagicMock()
        broken.poll.side_effect = RuntimeError("connection lost")
        healthy = MagicMock()
        healthy.poll.return_value = None

        with patch(f"{_MOD}.Consumer", side_effect=[broken, healthy]) as mock_consumer_cls:
            consumer = KafkaBlockedAccountsConsumer()
            with caplog.at_level(logging.ERROR):
                consumer.drain(_never_stop)
            broken.close.assert_called_once()
            assert "connection lost" in caplog.text

            consumer.drain(_never_stop)

        assert mock_consumer_cls.call_count == 2
        healthy.poll.assert_called_once_with(timeout=0)

    def test_a_close_that_fails_still_replaces_the_consumer(self, settings):
        _configure(settings)
        broken = MagicMock()
        broken.poll.side_effect = RuntimeError("connection lost")
        broken.close.side_effect = RuntimeError("close failed too")
        healthy = MagicMock()
        healthy.poll.return_value = None

        with patch(f"{_MOD}.Consumer", side_effect=[broken, healthy]):
            consumer = KafkaBlockedAccountsConsumer()
            consumer.drain(_never_stop)
            consumer.drain(_never_stop)

        healthy.poll.assert_called_once_with(timeout=0)

    def test_one_failing_region_does_not_stop_the_others(self, settings):
        _configure(
            settings,
            bootstrap_servers="broker-main:9093",
            regions={"eu-de": {"bootstrap_servers": "broker-eu:9093", "api_key": "eu-key", "user": "token"}},
        )
        broken = MagicMock()
        broken.poll.side_effect = RuntimeError("connection lost")
        healthy = MagicMock()
        healthy.poll.return_value = None

        def consumer_for(config):
            return broken if "broker-main" in config["bootstrap.servers"] else healthy

        with patch(f"{_MOD}.Consumer", side_effect=consumer_for):
            consumer = KafkaBlockedAccountsConsumer()
            consumer.drain(_never_stop)

        healthy.poll.assert_called_once_with(timeout=0)


class TestKafkaBlockedAccountsConsumerBadPayloads:
    """A payload nobody can handle must not stall its partition forever."""

    def test_unparseable_payload_is_logged_and_committed_over(self, settings, caplog):
        _configure(settings)
        kafka = MagicMock()
        garbage = MagicMock()
        garbage.error.return_value = None
        garbage.value.return_value = b"not json at all"
        kafka.poll.side_effect = [garbage] + [None] * 10

        with patch(f"{_MOD}.Consumer", return_value=kafka):
            consumer = KafkaBlockedAccountsConsumer()
            with caplog.at_level(logging.ERROR):
                consumer.drain(_never_stop)

        assert "Failed to process blocked account event" in caplog.text
        kafka.commit.assert_called_once_with(asynchronous=False)

    def test_a_bad_payload_does_not_stop_the_messages_behind_it(self, settings, caplog):
        _configure(settings)
        kafka = MagicMock()
        garbage = MagicMock()
        garbage.error.return_value = None
        garbage.value.return_value = b"not json at all"
        kafka.poll.side_effect = [garbage, _message({"account_id": "acc-after"})] + [None] * 10

        with patch(f"{_MOD}.Consumer", return_value=kafka):
            consumer = KafkaBlockedAccountsConsumer()
            with caplog.at_level(logging.INFO):
                consumer.drain(_never_stop)

        assert "account_id=acc-after" in caplog.text

    def test_event_with_missing_fields_is_logged_with_defaults(self, settings, caplog):
        _configure(settings)
        kafka = MagicMock()
        kafka.poll.side_effect = _messages_then_empty({})

        with patch(f"{_MOD}.Consumer", return_value=kafka):
            consumer = KafkaBlockedAccountsConsumer()
            with caplog.at_level(logging.INFO):
                consumer.drain(_never_stop)

        assert "account_id=None" in caplog.text
        assert "deleted=False" in caplog.text
