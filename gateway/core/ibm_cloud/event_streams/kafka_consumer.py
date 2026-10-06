"""Kafka consumer for blocked-account-plan events from IBM Cloud Event Streams."""

from __future__ import annotations

import json
import logging
import time
from threading import Thread

from confluent_kafka import Consumer

logger = logging.getLogger("gateway.ibm_cloud.event_streams_consumer")


class KafkaBlockedAccountsConsumer:
    """Consumes and logs blocked-account-plan events from Kafka across regions."""

    def __init__(self, region_configs: dict[str, dict], environment: str) -> None:
        """Initialize consumer with region credentials and environment.

        Args:
            region_configs: Dict mapping region → {bootstrap_servers, api_key, user}
            environment: Deployment environment (e.g., production, staging)
        """
        self._region_configs = region_configs
        self._environment = environment
        self._consumers: dict[str, Consumer] = {}

        self.blocked_accounts_topics = [
            f"quantum.{environment}.blocked-account-plans.v1",
            f"quantum.{environment}.blocked-account-plans-non-quantum.v1",
        ]
        self._blocked_accounts_group_id = f"qiskit-serverless-scheduler-blocked-accounts-{environment}"

        logger.info("Initialized blocked-accounts consumer for regions: %s", list(region_configs.keys()))

    def _get_consumer(self, region: str) -> Consumer:
        """Get or create a consumer for the given region."""
        if region in self._consumers:
            return self._consumers[region]

        config = self._region_configs[region]
        consumer = Consumer(
            {
                "bootstrap.servers": config["bootstrap_servers"],
                "security.protocol": "SASL_SSL",
                "sasl.mechanisms": "PLAIN",
                "sasl.username": config["user"],
                "sasl.password": config["api_key"],
                "group.id": self._blocked_accounts_group_id,
                "enable.auto.commit": False,
                "auto.offset.reset": "earliest",
            }
        )
        consumer.subscribe(self.blocked_accounts_topics)
        self._consumers[region] = consumer
        logger.debug(
            "Created consumer for region: region=%s topics=%s",
            region,
            ",".join(self.blocked_accounts_topics),
        )
        return consumer

    def _deserialize_blocked_account_event(self, msg) -> dict:
        """Deserialize a blocked-account-plan event (JSON payload)."""
        return json.loads(msg.value().decode("utf-8"))

    def _handle_blocked_account_event(self, event: dict, region: str) -> None:
        """Log a blocked-account event."""
        account_id = event.get("account_id")
        plan_id = event.get("plan_id")
        subscription_id = event.get("subscription_id")
        deleted = event.get("deleted", False)

        logger.info(
            "Blocked-account event: region=%s account_id=%s plan_id=%s subscription_id=%s deleted=%s",
            region,
            account_id,
            plan_id,
            subscription_id,
            deleted,
        )

    def _poll_region_continuously(self, region: str) -> None:
        """Continuously poll and log blocked-account events from one region."""
        while True:
            try:
                consumer = self._get_consumer(region)
                msg = consumer.poll(timeout=1.0)

                if msg is None:
                    continue

                if msg.error():
                    logger.error("Consumer error for region=%s error=%s", region, msg.error())
                    continue

                try:
                    event = self._deserialize_blocked_account_event(msg)
                    self._handle_blocked_account_event(event, region)
                    consumer.commit(asynchronous=False)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.error("Failed to process blocked account event: region=%s error=%s", region, str(e))

            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("Consumer error region=%s: %s", region, str(e), exc_info=True)
                self._consumers.pop(region, None)
                time.sleep(1)

    def consume_events(self) -> None:
        """Create one polling thread per region and block until all complete."""
        threads = []
        for region in self._region_configs:
            thread = Thread(target=self._poll_region_continuously, args=(region,), daemon=True)
            thread.start()
            threads.append(thread)
            logger.info("Started polling thread for region=%s", region)

        for thread in threads:
            thread.join()
