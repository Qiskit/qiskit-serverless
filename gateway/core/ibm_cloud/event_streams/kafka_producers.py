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

"""Per-region Kafka producer connections and the topic name, built once from environment
variables. Shared by KafkaEventStreamsClient (inline best-effort sends) and KafkaOutboxSender
(outbox sends): one producer per region for the whole scheduler process, not one per class that
happens to need Kafka.
"""

from __future__ import annotations

import logging
import os

from confluent_kafka import Producer

logger = logging.getLogger("gateway.ibm_cloud.event_streams_client")


class UnroutableRegionError(RuntimeError):
    """Raised when a message cannot be routed to a producer: the CRN's region could not be
    determined, or no producer is configured for that region."""


class KafkaProducers:
    """
    Configured from environment variables per region:
      EVENT_STREAMS_BOOTSTRAP_SERVERS         — comma-separated broker list (main region)
      EVENT_STREAMS_API_KEY                   — SASL/PLAIN password (main region)
      EVENT_STREAMS_USER                      — SASL/PLAIN username (default: 'token')
      EVENT_STREAMS_BOOTSTRAP_SERVERS_<REGION> — broker list for additional regions
      EVENT_STREAMS_API_KEY_<REGION>          — API key for additional regions
      EVENT_STREAMS_USER_<REGION>             — SASL/PLAIN username for additional regions
      EVENT_STREAMS_MAIN_REGION               — main region (default: us-east)
      ENVIRONMENT                             — deployment environment (e.g. production, staging)
    """

    def __init__(self) -> None:
        environment = os.environ["ENVIRONMENT"]

        self._producers: dict[str, Producer] = {}

        main_bootstrap_servers = os.environ.get("EVENT_STREAMS_BOOTSTRAP_SERVERS")
        main_api_key = os.environ.get("EVENT_STREAMS_API_KEY")
        main_user = os.environ.get("EVENT_STREAMS_USER", "token")
        main_region = os.environ.get("EVENT_STREAMS_MAIN_REGION", "us-east")

        if main_bootstrap_servers and main_api_key:
            logger.info("Registering main region producer: region=%s", main_region)
            self._producers[main_region] = self._create_producer(main_bootstrap_servers, main_api_key, main_user)
            self._main_region = main_region
        else:
            raise ValueError("EVENT_STREAMS_BOOTSTRAP_SERVERS and EVENT_STREAMS_API_KEY are required")

        for env_key in os.environ:
            if env_key.startswith("EVENT_STREAMS_BOOTSTRAP_SERVERS_"):
                suffix = env_key[len("EVENT_STREAMS_BOOTSTRAP_SERVERS_") :]
                region = suffix.lower().replace("_", "-")
                logger.info("Discovered environment variable for region: env_key=%s region=%s", env_key, region)
                bootstrap_servers = os.environ[env_key]
                api_key_env = f"EVENT_STREAMS_API_KEY_{suffix}"
                user_env = f"EVENT_STREAMS_USER_{suffix}"
                api_key = os.environ.get(api_key_env)
                user = os.environ.get(user_env, "token")

                if api_key is None:
                    raise ValueError(f"Region {region}: found {env_key} but missing {api_key_env}")

                logger.info("Registering regional producer: region=%s", region)
                self._producers[region] = self._create_producer(bootstrap_servers, api_key, user)

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
