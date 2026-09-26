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
Used by every KafkaSender instance (UpdateFleetsJobsStatuses' inline best-effort sends, and
DrainOutbox's outbox sends), each of which owns its own KafkaProducers rather than sharing one:
one producer per region per task that needs Kafka, not one for the whole process.
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
      settings.EVENT_STREAMS_BOOTSTRAP_SERVERS — comma-separated broker list (main region)
      settings.EVENT_STREAMS_API_KEY            — SASL/PLAIN password (main region)
      settings.EVENT_STREAMS_USER               — SASL/PLAIN username (default: 'token')
      settings.EVENT_STREAMS_REGIONS            — {region: {bootstrap_servers, api_key, user}}
                                                    for additional regions, discovered from
                                                    suffixed environment variables at settings
                                                    import time
      settings.EVENT_STREAMS_MAIN_REGION        — main region (default: us-east)
      settings.ENVIRONMENT                      — deployment environment (e.g. production, staging)

    settings.py itself already fails closed at import time if EVENT_STREAMS_ENABLED is true and
    the main credentials are missing, so this constructor (only ever called once that flag is
    true, see KafkaSender) can trust they are present and does not repeat that check.
    """

    def __init__(self) -> None:
        environment = settings.ENVIRONMENT
        if not environment:
            raise ValueError("ENVIRONMENT setting is required")

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

    def _create_producer(self, bootstrap_servers: str, api_key: str, user: str = "token") -> Producer:
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
            }
        )

    @staticmethod
    def _region_from_crn(instance_crn: str | None) -> str | None:
        """Extract the region from an instance CRN.

        The region is the 6th colon-delimited segment of the CRN
        (crn:v1:bluemix:public:quantum-computing:<region>:...).
        Returns None if the CRN is absent or has too few segments.
        """
        if not instance_crn:
            return None
        parts = instance_crn.split(":")
        if len(parts) > 5:
            return parts[5]
        return None

    def get(self, instance_crn: str | None) -> Producer:
        """Return the producer for instance_crn's region, or raise UnroutableRegionError."""
        region = self._region_from_crn(instance_crn)
        if region is None:
            raise UnroutableRegionError(f"KafkaProducers: Cannot determine region from CRN (crn={instance_crn})")
        producer = self._producers.get(region)
        if producer is None:
            raise UnroutableRegionError(f"KafkaProducers: No producer configured for region {region}")
        return producer
