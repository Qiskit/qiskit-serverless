# This code is part of a Qiskit project.
#
# (C) IBM 2026
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Kafka consumer for blocked-account-plan events from IBM Cloud Event Streams.

Driven by the scheduler loop (see scheduler/tasks/consume_blocked_account_events.py). The
scheduler is single-threaded, so drain() polls every region with a zero timeout and returns
within the tick instead of owning a thread that blocks the loop. librdkafka keeps fetching in
its own background threads between ticks, so messages are waiting in the local queue by the
time the next tick polls.

Configured from Django settings per region, exactly like KafkaProducers. See that class for
the settings involved.
"""

from __future__ import annotations

import json
import logging
from typing import Callable

from confluent_kafka import Consumer
from django.conf import settings

logger = logging.getLogger("gateway.ibm_cloud.event_streams_consumer")

# Most messages one region may contribute to a single scheduler tick, so a backlog is drained
# over several ticks rather than holding the loop inside one of them.
MAX_MESSAGES_PER_REGION_PER_TICK = 100


class KafkaBlockedAccountsConsumer:
    """Consumes and logs blocked-account-plan events from every configured region's Kafka bus."""

    def __init__(self) -> None:
        environment = settings.ENVIRONMENT
        # The suffixed regions come last, so one of them declaring the main region wins, the same
        # precedence KafkaProducers gives them.
        self._region_configs: dict[str, dict] = {
            settings.EVENT_STREAMS_MAIN_REGION: {
                "bootstrap_servers": settings.EVENT_STREAMS_BOOTSTRAP_SERVERS,
                "api_key": settings.EVENT_STREAMS_API_KEY,
                "user": settings.EVENT_STREAMS_USER,
            },
            **settings.EVENT_STREAMS_REGIONS,
        }
        self._consumers: dict[str, Consumer] = {}

        self.blocked_accounts_topics = [
            f"quantum.{environment}.blocked-account-plans.v1",
            f"quantum.{environment}.blocked-account-plans-non-quantum.v1",
        ]
        self._blocked_accounts_group_id = f"qiskit-serverless-scheduler-blocked-accounts-{environment}"

        logger.info(
            "Initialized blocked-accounts consumer for regions: %s",
            sorted(self._region_configs.keys()),
        )

    def drain(self, should_stop: Callable[[], bool]) -> None:
        """Handle whatever every region has queued, up to MAX_MESSAGES_PER_REGION_PER_TICK each."""
        for region in self._region_configs:
            if should_stop():
                logger.info("Kill signal received, stopping the blocked-account drain")
                return
            self._drain_region(region, should_stop)

    def _drain_region(self, region: str, should_stop: Callable[[], bool]) -> None:
        """Handle one region's queued messages and commit once for the batch."""
        try:
            consumer = self._get_consumer(region)
            handled = 0
            while handled < MAX_MESSAGES_PER_REGION_PER_TICK and not should_stop():
                msg = consumer.poll(timeout=0)
                if msg is None:
                    break

                if msg.error():
                    logger.error("Consumer error for region=%s error=%s", region, msg.error())
                    break

                handled += 1
                try:
                    event = self._deserialize_blocked_account_event(msg)
                    self._handle_blocked_account_event(event, region)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.error("Failed to process blocked account event: region=%s error=%s", region, str(e))

            if handled:
                # One commit for the whole batch, and after the fact: a payload that cannot be
                # handled is committed over rather than retried forever, which would stall its
                # partition behind it.
                consumer.commit(asynchronous=False)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Consumer error region=%s: %s", region, str(e), exc_info=True)
            # The next tick builds a fresh consumer; the tick itself paces the retry.
            self._discard_consumer(region)

    def _get_consumer(self, region: str) -> Consumer:
        """Get or create a consumer for the given region. One per region, cached, so successive
        ticks reuse the same consumer group member instead of joining the group again."""
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

    def _discard_consumer(self, region: str) -> None:
        """Close and forget a region's consumer. Closing matters: leaving it open would keep a
        zombie member in the consumer group, still holding the partitions its replacement needs."""
        consumer = self._consumers.pop(region, None)
        if consumer is None:
            return
        try:
            consumer.close()
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to close consumer for region=%s: %s", region, str(e))

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
