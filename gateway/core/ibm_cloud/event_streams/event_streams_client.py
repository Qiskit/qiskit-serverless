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

"""
IBM Event Streams client module.

Provides :class:`IBMEventStreamsClient` for publishing CloudEvents 1.0 usage
events to IBM Cloud Event Streams (Kafka).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone

try:
    from confluent_kafka import Producer
except ImportError:  # confluent-kafka is optional at import time
    Producer = None  # type: ignore[assignment,misc]

logger = logging.getLogger("gateway.ibm_cloud.event_streams_client")


class NoOpEventStreamsClient:
    """
    Drop-in replacement for IBMEventStreamsClient when EVENT_STREAMS_ENABLED is false.

    Logs each emit call at DEBUG level instead of publishing to Kafka.
    """

    def emit_job_started(self, job) -> None:
        """Log job_started at DEBUG level (no-op)."""
        logger.debug("job_id=%s [noop] emit_job_started", job.id)

    def emit_job_in_progress(self, job) -> None:
        """Log job_in_progress at DEBUG level (no-op)."""
        logger.debug("job_id=%s [noop] emit_job_in_progress", job.id)

    def emit_job_ended(self, job) -> None:
        """Log job_ended at DEBUG level (no-op)."""
        logger.debug("job_id=%s [noop] emit_job_ended", job.id)


class IBMEventStreamsClient:
    """
    Kafka producer client for IBM Cloud Event Streams.

    Publishes CloudEvents 1.0 usage events for Fleets jobs.
    Configured from environment variables:
      EVENT_STREAMS_BOOTSTRAP_SERVERS — comma-separated broker list
      EVENT_STREAMS_API_KEY           — SASL/PLAIN password
      ENVIRONMENT                     — deployment environment (e.g. production, staging)
    """

    def __init__(self) -> None:
        if Producer is None:
            raise RuntimeError(
                "confluent-kafka is not installed. Add confluent-kafka>=2.6.0,<3 to your dependencies."
            )

        bootstrap_servers = os.environ["EVENT_STREAMS_BOOTSTRAP_SERVERS"]
        api_key = os.environ["EVENT_STREAMS_API_KEY"]
        environment = os.environ["ENVIRONMENT"]

        self._producer = Producer(
            {
                "bootstrap.servers": bootstrap_servers,
                "security.protocol": "SASL_SSL",
                "sasl.mechanisms": "PLAIN",
                "sasl.username": "token",
                "sasl.password": api_key,
            }
        )
        self.topic = f"quantum.{environment}.function-usage.v1"

    def emit_job_started(self, job) -> None:
        """Publish a job_started event (usage_nanoseconds=0)."""
        self._publish(job, event_type="job_started", usage_nanoseconds=0)

    def emit_job_in_progress(self, job) -> None:
        """Publish a job_in_progress event with current usage."""
        self._publish(job, event_type="job_in_progress", usage_nanoseconds=self._usage_ns(job))

    def emit_job_ended(self, job) -> None:
        """Publish a job_ended event with final usage."""
        self._publish(job, event_type="job_ended", usage_nanoseconds=self._usage_ns(job))

    def _usage_ns(self, job) -> int:
        if job.running_started_at is None:
            return 0
        delta = datetime.now(timezone.utc) - job.running_started_at
        return int(delta.total_seconds() * 1e9)

    def _publish(self, job, *, event_type: str, usage_nanoseconds: int) -> None:
        now = datetime.now(timezone.utc)
        event = {
            "specversion": "1.0",
            "id": str(uuid.uuid4()),
            "source": "qiskit-serverless/scheduler/fleets",
            "type": self.topic,
            "time": now.isoformat(),
            "subject": str(job.id),
            "datacontenttype": "application/json",
            "data": {
                "event_type": event_type,
                "usage_nanoseconds": usage_nanoseconds,
                "instance_crn": job.instance_crn,
                "function_id": str(job.id),
            },
        }
        self._producer.produce(
            topic=self.topic,
            value=json.dumps(event).encode("utf-8"),
        )
        remaining = self._producer.flush(timeout=5)
        if remaining > 0:
            logger.warning("IBMEventStreamsClient: %d message(s) not delivered after flush timeout", remaining)
