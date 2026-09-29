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

"""Sender for every Kafka message this codebase publishes.

Usage: always get a sender through build_kafka_sender(), never by constructing KafkaSender
directly. It picks KafkaSender or NoOpSender for you based on
settings.EVENT_STREAMS_ENABLED, and KafkaSender builds its own KafkaProducers internally
(one Producer per region, keyed off the payload's CRN at send time), so there is nothing
else to wire up::

    from core.ibm_cloud.event_streams.kafka_sender import build_kafka_sender

    sender = build_kafka_sender()
    sender.send(payload)  # raises RuntimeError (or UnroutableRegionError) on failure

See outbox.py and update_fleets_jobs_statuses.py for the two real callers.
"""

import json
import logging

from django.conf import settings

from core.ibm_cloud.sender import Sender
from .kafka_producers import KafkaProducers

logger = logging.getLogger("gateway.ibm_cloud.event_streams_client")


class KafkaSender(Sender):
    """Sends a payload to Kafka as-is, plus `type`. See KafkaProducers for how producers/topic
    are configured and how a payload's CRN is routed to a region."""

    def __init__(self, producers: KafkaProducers | None = None) -> None:
        self._producers = producers or KafkaProducers()

    def send(self, payload: dict, timeout: int = 5) -> None:
        """Raises UnroutableRegionError (from KafkaProducers.get) or RuntimeError on failure."""
        message = {**payload, "type": self._producers.topic}
        instance_crn = (message.get("data") or {}).get("instance_crn")
        # This could raise UnroutableRegionError if:
        #    1 no data.instance_crn in the payload (impossible), or
        #    2 the crn is not valid (even more impossible yet), or
        #    3 there is no Kafka producer for the crn region
        producer = self._producers.get(instance_crn)

        try:
            # flush() returning 0 only means nothing is left outstanding, not that delivery succeeded:
            # a fast broker-side rejection (e.g. a topic ACL problem) calls the callback with an error
            # before flush() returns, so the callback has to record it for us to raise below.
            delivery_errors = []

            def on_delivery(err, msg):
                if err is not None:
                    self._log_delivery_error(err, msg)
                    delivery_errors.append(err)

            producer.produce(
                topic=self._producers.topic,
                key=message["subject"].encode("utf-8"),
                value=json.dumps(message).encode("utf-8"),
                callback=on_delivery,
            )
            remaining = producer.flush(timeout=timeout)
            if remaining > 0:
                raise RuntimeError(f"KafkaSender: {remaining} message(s) not delivered after flush timeout")
            if delivery_errors:
                raise RuntimeError(f"KafkaSender: message delivery failed: {delivery_errors[0]}")
        except Exception as e:
            raise RuntimeError(f"KafkaSender: Failed to publish event (id={message.get('id')}): {str(e)}") from e

    @staticmethod
    def _log_delivery_error(err, msg) -> None:
        logger.error(
            "Message delivery failed topic=%s partition=%s error=%s error_code=%s",
            msg.topic() if msg else "unknown",
            msg.partition() if msg else "unknown",
            err,
            err.code() if hasattr(err, "code") else "unknown",
        )


class NoOpSender(Sender):
    """Drop-in replacement for KafkaSender when EVENT_STREAMS_ENABLED is false. Logs instead of
    publishing."""

    def send(self, payload: dict) -> None:
        """Logs the payload instead of publishing it."""
        logger.info("payload=%s [noop] send", payload)


def build_kafka_sender() -> Sender:
    """Return a KafkaSender, or a NoOpSender when EVENT_STREAMS_ENABLED is false."""
    if settings.EVENT_STREAMS_ENABLED:
        logger.info("Initializing KafkaSender (EVENT_STREAMS_ENABLED=True)")
        return KafkaSender()
    logger.info("Initializing NoOpSender (EVENT_STREAMS_ENABLED=False)")
    return NoOpSender()
