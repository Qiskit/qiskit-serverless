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

from core.domain.crn import Crn

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
                # How long librdkafka keeps trying to deliver a message after produce(); the default is 5 min.
                # It is lowered to just under the 5 s flush timeout of KafkaSender so that a message that cannot
                # be delivered fails inside the flush window. That makes what flush() reports consistent: when it
                # returns, every message was either confirmed or failed, none is left pending. The outbox can then
                # safely retry the failed ones itself on its next tick, instead of leaving the message queued here
                # to be delivered minutes later, on top of the copy the outbox already produced again.
                "message.timeout.ms": 4000,
            }
        )

    def get(self, instance_crn: str | None) -> Producer:
        """Return the producer for instance_crn's region, or raise UnroutableRegionError."""
        crn = Crn.parse(instance_crn)
        if crn is None:
            # this is actually impossible: the user who created the job was authorized with the same crn, so the
            # existence of a job with a crn means the crn is actually valid
            raise UnroutableRegionError(f"KafkaProducers: Cannot determine region from CRN (crn={instance_crn})")
        producer = self._producers.get(crn.region)
        if producer is None:
            raise UnroutableRegionError(f"KafkaProducers: No producer configured for region {crn.region}")
        return producer
