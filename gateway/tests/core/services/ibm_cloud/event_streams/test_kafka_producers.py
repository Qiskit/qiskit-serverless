"""Unit tests for KafkaProducers: producer/topic setup from Django settings, and region
routing. This logic used to live on the client class that sent events inline; it moved here once
KafkaSender needed the exact same producer/region routing for the outbox."""

import logging
from unittest.mock import MagicMock, patch

import pytest

from core.ibm_cloud.event_streams.kafka_producers import KafkaProducers, UnroutableRegionError

_MOD = "core.ibm_cloud.event_streams.kafka_producers"


def _configure(settings, **overrides):
    """Set the Event Streams settings KafkaProducers reads, with sane defaults."""
    settings.ENVIRONMENT = overrides.get("environment", "staging")
    settings.EVENT_STREAMS_BOOTSTRAP_SERVERS = overrides.get("bootstrap_servers", "broker1:9093")
    settings.EVENT_STREAMS_API_KEY = overrides.get("api_key", "my-key")
    settings.EVENT_STREAMS_USER = overrides.get("user", "token")
    settings.EVENT_STREAMS_MAIN_REGION = overrides.get("main_region", "us-east")
    settings.EVENT_STREAMS_REGIONS = overrides.get("regions", {})


class TestKafkaProducersSetup:
    def test_producer_configured_with_sasl_plain_tls(self, settings):
        _configure(settings, bootstrap_servers="broker1:9093", api_key="my-key", environment="staging")

        with patch(f"{_MOD}.Producer") as mock_producer_cls:
            KafkaProducers()

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

    def test_topic_constructed_from_environment(self, settings):
        _configure(settings, bootstrap_servers="b:9093", api_key="k", environment="staging")

        with patch(f"{_MOD}.Producer"):
            producers = KafkaProducers()

        assert producers.topic == "quantum.staging.function-usage.v1"

    def test_custom_user_in_main_region(self, settings):
        _configure(
            settings,
            bootstrap_servers="broker1:9093",
            api_key="my-key",
            user="custom-user",
            environment="staging",
        )

        with patch(f"{_MOD}.Producer") as mock_producer_cls:
            KafkaProducers()

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

    def test_custom_user_in_regional_producer(self, settings):
        _configure(
            settings,
            bootstrap_servers="broker-main:9093",
            api_key="main-key",
            user="main-user",
            environment="production",
            regions={"au-syd": {"bootstrap_servers": "broker-au:9093", "api_key": "au-key", "user": "custom-au-user"}},
        )

        with patch(f"{_MOD}.Producer") as mock_producer_cls:
            KafkaProducers()

        calls = mock_producer_cls.call_args_list
        assert len(calls) == 2
        main_call = [c for c in calls if "broker-main" in str(c)][0]
        au_call = [c for c in calls if "broker-au" in str(c)][0]
        assert main_call[0][0]["sasl.username"] == "main-user"
        assert au_call[0][0]["sasl.username"] == "custom-au-user"

    def test_main_region_producer_created(self, settings):
        _configure(settings, bootstrap_servers="broker1:9093", api_key="main-key", environment="production")

        with patch(f"{_MOD}.Producer") as mock_producer_cls:
            producers = KafkaProducers()

        assert "us-east" in producers._producers
        mock_producer_cls.assert_called_once()

    def test_regional_producers_created_from_settings(self, settings):
        _configure(
            settings,
            bootstrap_servers="broker-main:9093",
            api_key="main-key",
            environment="production",
            regions={"eu-de": {"bootstrap_servers": "broker-eu:9093", "api_key": "eu-key", "user": "token"}},
        )

        with patch(f"{_MOD}.Producer") as mock_producer_cls:
            producers = KafkaProducers()

        assert "eu-de" in producers._producers
        assert mock_producer_cls.call_count == 2

    def test_event_streams_main_region_respected(self, settings):
        _configure(
            settings,
            bootstrap_servers="broker1:9093",
            api_key="key",
            main_region="eu-gb",
            environment="production",
        )

        with patch(f"{_MOD}.Producer"):
            producers = KafkaProducers()

        assert producers._main_region == "eu-gb"
        assert "eu-gb" in producers._producers

    def test_startup_log_line(self, settings, caplog):
        _configure(
            settings,
            bootstrap_servers="broker-main:9093",
            api_key="main-key",
            environment="production",
            regions={"eu-de": {"bootstrap_servers": "broker-eu:9093", "api_key": "eu-key", "user": "token"}},
        )

        with patch(f"{_MOD}.Producer"):
            with caplog.at_level(logging.INFO):
                KafkaProducers()

        assert "Event Streams producers initialized" in caplog.text
        assert "regions=" in caplog.text
        assert "main=us-east" in caplog.text


class TestKafkaProducersRegionLookup:
    def test_get_selects_the_right_producer_by_region(self, settings):
        mock_producer_main = MagicMock()
        mock_producer_regional = MagicMock()

        def create_producer_side_effect(config):
            if "broker-main" in config.get("bootstrap.servers", ""):
                return mock_producer_main
            if "broker-regional" in config.get("bootstrap.servers", ""):
                return mock_producer_regional
            return MagicMock()

        _configure(
            settings,
            bootstrap_servers="broker-main:9093",
            api_key="main-key",
            environment="production",
            regions={
                "au-syd": {"bootstrap_servers": "broker-regional:9093", "api_key": "regional-key", "user": "token"}
            },
        )

        with patch(f"{_MOD}.Producer", side_effect=create_producer_side_effect):
            producers = KafkaProducers()

        assert producers.get("crn:v1:bluemix:public:quantum-computing:us-east:a/abc:def::") is mock_producer_main
        assert producers.get("crn:v1:bluemix:public:quantum-computing:au-syd:a/abc:def::") is mock_producer_regional

    def test_unconfigured_region_raises_unroutable(self, settings):
        _configure(settings, bootstrap_servers="b:9093", api_key="k", environment="production")

        with patch(f"{_MOD}.Producer"):
            producers = KafkaProducers()

        with pytest.raises(UnroutableRegionError, match="No producer configured for region au-syd"):
            producers.get("crn:v1:bluemix:public:quantum-computing:au-syd:a/abc:def::")

    def test_null_crn_raises_unroutable(self, settings):
        _configure(settings, bootstrap_servers="b:9093", api_key="k", environment="production")

        with patch(f"{_MOD}.Producer"):
            producers = KafkaProducers()

        with pytest.raises(UnroutableRegionError, match="Cannot determine region from CRN"):
            producers.get(None)

    def test_malformed_crn_raises_unroutable(self, settings):
        _configure(settings, bootstrap_servers="b:9093", api_key="k", environment="production")

        with patch(f"{_MOD}.Producer"):
            producers = KafkaProducers()

        with pytest.raises(UnroutableRegionError, match="Cannot determine region from CRN"):
            producers.get("not:a:valid:crn")

    def test_unroutable_region_error_is_a_runtime_error(self):
        """A broad `except RuntimeError` elsewhere in the codebase must still catch this, so it
        has to remain a RuntimeError subclass."""
        assert issubclass(UnroutableRegionError, RuntimeError)
