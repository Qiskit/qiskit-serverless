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
from .regions import region_configs, sasl_config

logger = logging.getLogger("gateway.ibm_cloud.event_streams_client")


class UnroutableRegionError(RuntimeError):
    """Raised when a message cannot be routed to a producer: the CRN's region could not be
    determined, or no producer is configured for that region."""


class KafkaProducers:
    """
    One producer per region in regions.region_configs(); see that module for the settings involved.
    The topic is namespaced by settings.ENVIRONMENT ("production" or "staging").
    """

    def __init__(self) -> None:
        environment = settings.ENVIRONMENT
        self._main_region = settings.EVENT_STREAMS_MAIN_REGION
        self._producers: dict[str, Producer] = {}

        for region, config in region_configs().items():
            logger.info("Registering producer: region=%s", region)
            self._producers[region] = self._create_producer(config)

        self.topic = f"quantum.{environment}.function-usage.v1"

        regions = sorted(self._producers.keys())
        logger.info(
            "Event Streams producers initialized: regions=%s (main=%s)",
            regions,
            self._main_region,
        )

    @staticmethod
    def _create_producer(config: dict[str, str]) -> Producer:
        """Create and return a Kafka producer for one region's config."""
        return Producer(
            {
                **sasl_config(config),
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
