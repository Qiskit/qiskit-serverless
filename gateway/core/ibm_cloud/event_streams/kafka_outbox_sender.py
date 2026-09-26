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

"""Sender for the outbox's "billing" channel: publishes an already-built payload to Kafka,
unchanged, except for the `type` field. Never touches Job, Program, or licensing: see
core/domain/billing_events.py for what builds the payload this sends.
"""

import json
import logging

from .kafka_producers import KafkaProducers

logger = logging.getLogger("gateway.ibm_cloud.event_streams_client")


class KafkaOutboxSender:
    """Sends an outbox payload to Kafka as-is. `type` (the Kafka topic name) is added here, at
    send time, not by the builder: see the design doc, section 6, for why. Every retry of the
    same row adds the same `type`, so the message stays byte-identical across retries.
    """

    def __init__(self, producers: KafkaProducers | None = None) -> None:
        self._producers = producers or KafkaProducers()

    def send(self, payload: dict) -> None:
        """Raises UnroutableRegionError (from KafkaProducers.get) or RuntimeError on failure."""
        message = {**payload, "type": self._producers.topic}
        instance_crn = message["data"]["instance_crn"]
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
                raise RuntimeError(f"KafkaOutboxSender: {remaining} message(s) not delivered after flush timeout")
        except Exception as e:
            raise RuntimeError(f"KafkaOutboxSender: Failed to publish event (id={message.get('id')}): {str(e)}") from e

    def _delivery_callback(self, err, msg):
        if err is not None:
            logger.error(
                "Message delivery failed topic=%s partition=%s error=%s error_code=%s",
                msg.topic() if msg else "unknown",
                msg.partition() if msg else "unknown",
                err,
                err.code() if hasattr(err, "code") else "unknown",
            )


class NoOpOutboxSender:
    """Drop-in replacement for KafkaOutboxSender when EVENT_STREAMS_ENABLED is false. Logs
    instead of publishing, matching NoOpEventStreamsClient."""

    def send(self, payload: dict) -> None:
        """Logs the payload instead of publishing it."""
        logger.info("payload=%s [noop] outbox send", payload)
