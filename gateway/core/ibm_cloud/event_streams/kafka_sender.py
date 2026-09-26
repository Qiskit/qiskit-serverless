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

"""Sender for every Kafka message this codebase publishes: an already-built payload goes out
unchanged, except for the `type` field (the Kafka topic name), which is added here, at send
time, not by whichever builder made the payload (see core/domain/usage_events.py for that).
Every retry of the same payload therefore adds the same `type`, so a message that gets retried
(from the outbox) stays byte-identical across attempts.

The same sender serves two callers that never know about each other: UpdateFleetsJobsStatuses
sends a payload right after building it, inline, best-effort; DrainOutbox sends a payload it
read back from an Outbox row, possibly long after it was built, with retries. Neither the sender
nor KafkaProducers cares which case it is in.
"""

import json
import logging

from .kafka_producers import KafkaProducers

logger = logging.getLogger("gateway.ibm_cloud.event_streams_client")


class KafkaSender:
    """Sends a payload to Kafka as-is, plus `type`. See KafkaProducers for how producers/topic
    are configured and how a payload's CRN is routed to a region."""

    def __init__(self, producers: KafkaProducers | None = None) -> None:
        self._producers = producers or KafkaProducers()

    def send(self, payload: dict) -> None:
        """Raises UnroutableRegionError (from KafkaProducers.get) or RuntimeError on failure."""
        message = {**payload, "type": self._producers.topic}
        instance_crn = (message.get("data") or {}).get("instance_crn")
        producer = self._producers.get(instance_crn)  # raises UnroutableRegionError

        try:
            producer.produce(
                topic=self._producers.topic,
                key=message["subject"].encode("utf-8"),
                value=json.dumps(message).encode("utf-8"),
                callback=self._delivery_callback,
            )
            remaining = producer.flush(timeout=5)
            if remaining > 0:
                raise RuntimeError(f"KafkaSender: {remaining} message(s) not delivered after flush timeout")
        except Exception as e:
            raise RuntimeError(f"KafkaSender: Failed to publish event (id={message.get('id')}): {str(e)}") from e

    def _delivery_callback(self, err, msg):
        if err is not None:
            logger.error(
                "Message delivery failed topic=%s partition=%s error=%s error_code=%s",
                msg.topic() if msg else "unknown",
                msg.partition() if msg else "unknown",
                err,
                err.code() if hasattr(err, "code") else "unknown",
            )


class NoOpSender:
    """Drop-in replacement for KafkaSender when EVENT_STREAMS_ENABLED is false. Logs instead of
    publishing."""

    def send(self, payload: dict) -> None:
        """Logs the payload instead of publishing it."""
        logger.info("payload=%s [noop] send", payload)
