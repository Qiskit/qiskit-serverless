"""Unit tests for the per-region Event Streams settings shared by the producers and the consumers."""

from core.ibm_cloud.event_streams.regions import region_configs, sasl_config


def _configure(settings, main_region="us-east", regions=None):
    settings.EVENT_STREAMS_MAIN_REGION = main_region
    settings.EVENT_STREAMS_BOOTSTRAP_SERVERS = "broker-main:9093"
    settings.EVENT_STREAMS_API_KEY = "main-key"
    settings.EVENT_STREAMS_USER = "main-user"
    settings.EVENT_STREAMS_REGIONS = regions or {}


class TestRegionConfigs:
    def test_the_main_region_comes_from_the_unsuffixed_settings(self, settings):
        _configure(settings, main_region="eu-gb")

        assert region_configs() == {
            "eu-gb": {"bootstrap_servers": "broker-main:9093", "api_key": "main-key", "user": "main-user"}
        }

    def test_suffixed_regions_follow_the_main_region(self, settings):
        eu_de = {"bootstrap_servers": "broker-eu:9093", "api_key": "eu-key", "user": "token"}
        _configure(settings, regions={"eu-de": eu_de})

        configs = region_configs()

        assert list(configs) == ["us-east", "eu-de"]
        assert configs["eu-de"] == eu_de

    def test_a_suffixed_region_declaring_the_main_region_wins(self, settings):
        override = {"bootstrap_servers": "broker-override:9093", "api_key": "k", "user": "token"}
        _configure(settings, regions={"us-east": override})

        assert region_configs() == {"us-east": override}


class TestSaslConfig:
    def test_sasl_plain_over_tls(self):
        config = {"bootstrap_servers": "broker:9093", "api_key": "key", "user": "user"}

        assert sasl_config(config) == {
            "bootstrap.servers": "broker:9093",
            "security.protocol": "SASL_SSL",
            "sasl.mechanisms": "PLAIN",
            "sasl.username": "user",
            "sasl.password": "key",
        }
