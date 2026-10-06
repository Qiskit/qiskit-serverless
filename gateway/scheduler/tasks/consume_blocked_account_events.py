"""Consume blocked-account-plan events from Kafka."""

import logging

from django.conf import settings

from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from .task import SchedulerTask

logger = logging.getLogger("scheduler.ConsumeBlockedAccountEvents")


class ConsumeBlockedAccountEvents(SchedulerTask):
    """Consume blocked-account-plan events from Kafka."""

    def __init__(self, kill_signal: KillSignal, metrics: SchedulerMetrics):
        self.kill_signal = kill_signal
        self.metrics = metrics

    def run(self) -> None:
        """Poll and process blocked-account events from Kafka."""
        if not settings.EVENT_STREAMS_ENABLED:
            logger.debug("EVENT_STREAMS_ENABLED is False, skipping blocked-account consumer")
            return

        try:
            from core.ibm_cloud.event_streams.kafka_consumer import (  # pylint: disable=import-outside-toplevel
                KafkaBlockedAccountsConsumer,
            )

            import os  # pylint: disable=import-outside-toplevel

            # Build region configs from environment variables
            environment = os.environ.get("ENVIRONMENT", "production")
            main_region = os.environ.get("EVENT_STREAMS_MAIN_REGION", "us-east")
            main_bootstrap_servers = os.environ.get("EVENT_STREAMS_BOOTSTRAP_SERVERS")
            main_api_key = os.environ.get("EVENT_STREAMS_API_KEY")
            main_user = os.environ.get("EVENT_STREAMS_USER", "token")

            region_configs = {}
            if main_bootstrap_servers and main_api_key:
                region_configs[main_region] = {
                    "bootstrap_servers": main_bootstrap_servers,
                    "api_key": main_api_key,
                    "user": main_user,
                }

            # Discover regional configs by scanning for suffixed env vars
            for env_key in os.environ:
                if env_key.startswith("EVENT_STREAMS_BOOTSTRAP_SERVERS_"):
                    suffix = env_key[len("EVENT_STREAMS_BOOTSTRAP_SERVERS_") :]
                    region = suffix.lower().replace("_", "-")
                    bootstrap_servers = os.environ[env_key]
                    api_key = os.environ.get(f"EVENT_STREAMS_API_KEY_{suffix}")
                    user = os.environ.get(f"EVENT_STREAMS_USER_{suffix}", "token")
                    if api_key:
                        region_configs[region] = {
                            "bootstrap_servers": bootstrap_servers,
                            "api_key": api_key,
                            "user": user,
                        }

            if not region_configs:
                logger.debug("No EVENT_STREAMS credentials configured, skipping blocked-account consumer")
                return

            consumer = KafkaBlockedAccountsConsumer(region_configs, environment)
            logger.debug("Starting blocked-account events consumer")
            consumer.consume_events()
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Failed to consume blocked-account events: %s", str(e), exc_info=True)
