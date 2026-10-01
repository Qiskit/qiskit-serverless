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

"""Per-region Kafka producer connections and the topic name, built once from Django settings.
Used by every KafkaSender instance (the one of JobTransitionService, for the inline best-effort
sends, created once and shared by the scheduler tasks that change a job status; and the one of
OutboxTask, for the outbox sends), each of which owns its own KafkaProducers rather than sharing
one: one producer per region per owner, not one for the whole process.
"""

from __future__ import annotations

import logging

from confluent_kafka import Producer
from django.conf import settings

logger = logging.getLogger("gateway.ibm_cloud.event_streams_client")


class UnroutableRegionError(RuntimeError):
    """Raised when a message cannot be routed to a producer: the CRN's region could not be
    determined, or no producer is configured for that region."""


class KafkaProducers:
    """
    Configured from Django settings (main/settings.py) per region:
      settings.ENVIRONMENT:                     "production" or "staging"

      settings.EVENT_STREAMS_BOOTSTRAP_SERVERS: comma-separated broker list (main region)
      settings.EVENT_STREAMS_API_KEY:           SASL/PLAIN password (main region)
      settings.EVENT_STREAMS_USER:              SASL/PLAIN username
      settings.EVENT_STREAMS_REGIONS:           {region: {bootstrap_servers, api_key, user}}
        for additional regions, discovered from suffixed environment variables at settings import time
      settings.EVENT_STREAMS_MAIN_REGION:       main region (default: us-east)
    """

    def __init__(self) -> None:
        environment = settings.ENVIRONMENT
        self._producers: dict[str, Producer] = {}

        main_region = settings.EVENT_STREAMS_MAIN_REGION
        logger.info("Registering main region producer: region=%s", main_region)
        self._producers[main_region] = self._create_producer(
            settings.EVENT_STREAMS_BOOTSTRAP_SERVERS, settings.EVENT_STREAMS_API_KEY, settings.EVENT_STREAMS_USER
        )
        self._main_region = main_region

        for region, config in settings.EVENT_STREAMS_REGIONS.items():
            logger.info("Registering regional producer: region=%s", region)
            self._producers[region] = self._create_producer(
                config["bootstrap_servers"], config["api_key"], config["user"]
            )

        self.topic = f"quantum.{environment}.function-usage.v1"

        regions = sorted(self._producers.keys())
        logger.info(
            "Event Streams producers initialized: regions=%s (main=%s)",
            regions,
            main_region,
        )

    @staticmethod
    def _create_producer(bootstrap_servers: str, api_key: str, user: str = "token") -> Producer:
        """Create and return a Kafka producer with the given credentials."""
        return Producer(
            {
                "bootstrap.servers": bootstrap_servers,
                "security.protocol": "SASL_SSL",
                "sasl.mechanisms": "PLAIN",
                "sasl.username": user,
                "sasl.password": api_key,
                "enable.idempotence": True,
                "acks": "all",
                # How long librdkafka keeps trying to deliver a message after produce() (default 5 min). It is
                # kept just under the 5 s flush timeout of KafkaSender, so a message that cannot be delivered
                # in time fails inside flush() instead of lingering in the queue and being delivered minutes
                # later, on top of the copy the outbox produces again on the next tick.
                "message.timeout.ms": 4000,
            }
        )

    @staticmethod
    def region(instance_crn: str | None) -> str | None:
        """The region in instance_crn, or None if it cannot be parsed out of it."""
        parts = instance_crn.split(":") if isinstance(instance_crn, str) else []
        return parts[5] if len(parts) > 6 else None

    def get(self, instance_crn: str | None) -> Producer:
        """Return the producer for instance_crn's region, or raise UnroutableRegionError."""
        region = self.region(instance_crn)
        if region is None:
            # this is actually impossible: the user who created the job was authorized with the same crn, so the
            # existence of a job with a crn means the crn is actually valid
            raise UnroutableRegionError(f"KafkaProducers: Cannot determine region from CRN (crn={instance_crn})")
        producer = self._producers.get(region)
        if producer is None:
            raise UnroutableRegionError(f"KafkaProducers: No producer configured for region {region}")
        return producer
