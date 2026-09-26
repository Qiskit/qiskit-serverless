"""Unit tests for KafkaProducers: producer/topic setup from environment variables, and region
routing. Ported from test_event_streams_client.py, whose KafkaEventStreamsClient no longer owns
this logic."""

import logging
import os
from unittest.mock import MagicMock, patch

import pytest

from core.ibm_cloud.event_streams.kafka_producers import KafkaProducers, UnroutableRegionError

_MOD = "core.ibm_cloud.event_streams.kafka_producers"


class TestKafkaProducersSetup:
    def test_producer_configured_with_sasl_plain_tls(self):
        with patch(f"{_MOD}.Producer") as mock_producer_cls:
            with patch.dict(
                os.environ,
                {
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS": "broker1:9093",
                    "EVENT_STREAMS_API_KEY": "my-key",
                    "ENVIRONMENT": "staging",
                },
            ):
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

    def test_topic_constructed_from_environment(self):
        with patch(f"{_MOD}.Producer"):
            with patch.dict(
                os.environ,
                {
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS": "b:9093",
                    "EVENT_STREAMS_API_KEY": "k",
                    "ENVIRONMENT": "staging",
                },
            ):
                producers = KafkaProducers()

        assert producers.topic == "quantum.staging.function-usage.v1"

    def test_custom_user_in_main_region(self):
        with patch(f"{_MOD}.Producer") as mock_producer_cls:
            with patch.dict(
                os.environ,
                {
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS": "broker1:9093",
                    "EVENT_STREAMS_API_KEY": "my-key",
                    "EVENT_STREAMS_USER": "custom-user",
                    "ENVIRONMENT": "staging",
                },
            ):
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

    def test_custom_user_in_regional_producer(self):
        with patch(f"{_MOD}.Producer") as mock_producer_cls:
            with patch.dict(
                os.environ,
                {
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS": "broker-main:9093",
                    "EVENT_STREAMS_API_KEY": "main-key",
                    "EVENT_STREAMS_USER": "main-user",
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS_AU_SYD": "broker-au:9093",
                    "EVENT_STREAMS_API_KEY_AU_SYD": "au-key",
                    "EVENT_STREAMS_USER_AU_SYD": "custom-au-user",
                    "ENVIRONMENT": "production",
                },
                clear=True,
            ):
                KafkaProducers()

        calls = mock_producer_cls.call_args_list
        assert len(calls) == 2
        main_call = [c for c in calls if "broker-main" in str(c)][0]
        au_call = [c for c in calls if "broker-au" in str(c)][0]
        assert main_call[0][0]["sasl.username"] == "main-user"
        assert au_call[0][0]["sasl.username"] == "custom-au-user"

    def test_main_region_producer_from_unsuffixed_vars(self):
        with patch(f"{_MOD}.Producer") as mock_producer_cls:
            with patch.dict(
                os.environ,
                {
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS": "broker1:9093",
                    "EVENT_STREAMS_API_KEY": "main-key",
                    "ENVIRONMENT": "production",
                },
                clear=True,
            ):
                producers = KafkaProducers()

        assert "us-east" in producers._producers
        mock_producer_cls.assert_called_once()

    def test_suffixed_vars_discovered_by_scan(self):
        with patch(f"{_MOD}.Producer") as mock_producer_cls:
            with patch.dict(
                os.environ,
                {
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS": "broker-main:9093",
                    "EVENT_STREAMS_API_KEY": "main-key",
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS_EU_DE": "broker-eu:9093",
                    "EVENT_STREAMS_API_KEY_EU_DE": "eu-key",
                    "ENVIRONMENT": "production",
                },
                clear=True,
            ):
                producers = KafkaProducers()

        assert "eu-de" in producers._producers
        assert mock_producer_cls.call_count == 2

    def test_event_streams_main_region_respected(self):
        with patch(f"{_MOD}.Producer"):
            with patch.dict(
                os.environ,
                {
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS": "broker1:9093",
                    "EVENT_STREAMS_API_KEY": "key",
                    "EVENT_STREAMS_MAIN_REGION": "eu-gb",
                    "ENVIRONMENT": "production",
                },
                clear=True,
            ):
                producers = KafkaProducers()

        assert producers._main_region == "eu-gb"
        assert "eu-gb" in producers._producers

    def test_broker_list_without_matching_api_key_raises_at_init(self):
        with patch(f"{_MOD}.Producer"):
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
                    KafkaProducers()

    def test_startup_log_line(self, caplog):
        with patch(f"{_MOD}.Producer"):
            with patch.dict(
                os.environ,
                {
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS": "broker-main:9093",
                    "EVENT_STREAMS_API_KEY": "main-key",
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS_EU_DE": "broker-eu:9093",
                    "EVENT_STREAMS_API_KEY_EU_DE": "eu-key",
                    "ENVIRONMENT": "production",
                },
                clear=True,
            ):
                with caplog.at_level(logging.INFO):
                    KafkaProducers()

        assert "Event Streams producers initialized" in caplog.text
        assert "regions=" in caplog.text
        assert "main=us-east" in caplog.text

    def test_suffixed_env_var_eu_de_maps_to_eu_de_region(self):
        """EVENT_STREAMS_BOOTSTRAP_SERVERS_EU_DE maps to region 'eu-de' (not '_')."""
        with patch(f"{_MOD}.Producer"):
            with patch.dict(
                os.environ,
                {
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS": "broker-main:9093",
                    "EVENT_STREAMS_API_KEY": "main-key",
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS_EU_DE": "broker-eu:9093",
                    "EVENT_STREAMS_API_KEY_EU_DE": "eu-key",
                    "ENVIRONMENT": "production",
                },
                clear=True,
            ):
                producers = KafkaProducers()

        assert "eu-de" in producers._producers
        assert "_" not in producers._producers


class TestKafkaProducersRegionLookup:
    def test_region_from_crn_extracts_correctly(self):
        assert (
            KafkaProducers._region_from_crn("crn:v1:bluemix:public:quantum-computing:us-east:a/abc:def::") == "us-east"
        )
        assert KafkaProducers._region_from_crn("crn:v1:bluemix:public:quantum-computing:eu-de:a/abc:def::") == "eu-de"

    def test_region_from_crn_returns_none_for_invalid_crn(self):
        assert KafkaProducers._region_from_crn(None) is None
        assert KafkaProducers._region_from_crn("") is None
        assert KafkaProducers._region_from_crn("not:a:valid:crn") is None

    def test_get_selects_the_right_producer_by_region(self):
        mock_producer_main = MagicMock()
        mock_producer_regional = MagicMock()

        def create_producer_side_effect(config):
            if "broker-main" in config.get("bootstrap.servers", ""):
                return mock_producer_main
            if "broker-regional" in config.get("bootstrap.servers", ""):
                return mock_producer_regional
            return MagicMock()

        with patch(f"{_MOD}.Producer", side_effect=create_producer_side_effect):
            with patch.dict(
                os.environ,
                {
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS": "broker-main:9093",
                    "EVENT_STREAMS_API_KEY": "main-key",
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS_AU_SYD": "broker-regional:9093",
                    "EVENT_STREAMS_API_KEY_AU_SYD": "regional-key",
                    "ENVIRONMENT": "production",
                },
                clear=True,
            ):
                producers = KafkaProducers()

        assert producers.get("crn:v1:bluemix:public:quantum-computing:us-east:a/abc:def::") is mock_producer_main
        assert producers.get("crn:v1:bluemix:public:quantum-computing:au-syd:a/abc:def::") is mock_producer_regional

    def test_unconfigured_region_raises_unroutable(self):
        with patch(f"{_MOD}.Producer"):
            with patch.dict(
                os.environ,
                {
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS": "b:9093",
                    "EVENT_STREAMS_API_KEY": "k",
                    "ENVIRONMENT": "production",
                },
                clear=True,
            ):
                producers = KafkaProducers()

        with pytest.raises(UnroutableRegionError, match="No producer configured for region au-syd"):
            producers.get("crn:v1:bluemix:public:quantum-computing:au-syd:a/abc:def::")

    def test_null_crn_raises_unroutable(self):
        with patch(f"{_MOD}.Producer"):
            with patch.dict(
                os.environ,
                {
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS": "b:9093",
                    "EVENT_STREAMS_API_KEY": "k",
                    "ENVIRONMENT": "production",
                },
                clear=True,
            ):
                producers = KafkaProducers()

        with pytest.raises(UnroutableRegionError, match="Cannot determine region from CRN"):
            producers.get(None)

    def test_malformed_crn_raises_unroutable(self):
        with patch(f"{_MOD}.Producer"):
            with patch.dict(
                os.environ,
                {
                    "EVENT_STREAMS_BOOTSTRAP_SERVERS": "b:9093",
                    "EVENT_STREAMS_API_KEY": "k",
                    "ENVIRONMENT": "production",
                },
                clear=True,
            ):
                producers = KafkaProducers()

        with pytest.raises(UnroutableRegionError, match="Cannot determine region from CRN"):
            producers.get("not:a:valid:crn")

    def test_unroutable_region_error_is_a_runtime_error(self):
        """A broad `except RuntimeError` elsewhere in the codebase must still catch this, so it
        has to remain a RuntimeError subclass."""
        assert issubclass(UnroutableRegionError, RuntimeError)
