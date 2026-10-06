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

The outbox uses sender.send_batch(messages) instead, which never raises and returns the keys the broker
confirmed.

See outbox.py and core/services/job_transitions.py for the two real callers.
"""

import json
import logging

from django.conf import settings

from core.ibm_cloud.sender import PendingMessage, Sender
from .kafka_producers import KafkaProducers

logger = logging.getLogger("gateway.ibm_cloud.event_streams_client")


class KafkaSender(Sender):
    """Sends a payload to Kafka as-is, plus `type`. See KafkaProducers for how producers/topic
    are configured and how a payload's CRN is routed to a region."""

    def __init__(self, producers: KafkaProducers | None = None) -> None:
        self._producers = producers or KafkaProducers()

    def send(self, payload: dict, timeout: float = 5) -> None:
        """Raises UnroutableRegionError (from KafkaProducers.get) or RuntimeError on failure.

        With timeout=0 it does not wait for the broker: the message is queued in the producer, which delivers it
        in the background and gives up on it after message.timeout.ms. Only a message that cannot be routed or
        queued raises. A delivery that fails later is logged by the callback, and poll(0) serves the reports of
        earlier messages."""
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
            if timeout == 0:
                producer.poll(0)
                return
            remaining = producer.flush(timeout=timeout)
            if remaining > 0:
                raise RuntimeError(f"KafkaSender: {remaining} message(s) not delivered after flush timeout")
            if delivery_errors:
                raise RuntimeError(f"KafkaSender: message delivery failed: {delivery_errors[0]}")
        except Exception as e:
            raise RuntimeError(f"KafkaSender: Failed to publish event (id={message.get('id')}): {str(e)}") from e

    def flush(self, timeout: float = 5) -> None:
        """Wait for the messages still queued in every producer. Meant for shutdown, so best effort messages
        queued by send(timeout=0) are not lost when the process stops."""
        self._producers.flush(timeout)

    def send_batch(self, messages: list[PendingMessage], timeout: float = 5) -> set[int]:
        """Produce every payload, flush each producer once, and return the keys the broker confirmed
        through their delivery callback. A payload that cannot be routed or produced, is rejected by
        the broker, or is still outstanding when the flush times out is left out of the result. The
        timeout applies to each producer's flush. A message left outstanding may still be delivered
        later and then sent again from its row, which is accepted (at-least-once)."""
        delivered: set[int] = set()
        producers_used = {}

        for pending in messages:
            key = pending.key
            try:
                message = {**pending.payload, "type": self._producers.topic}
                producer = self._producers.get(self._instance_crn(message))
                producer.produce(
                    topic=self._producers.topic,
                    key=message["subject"].encode("utf-8"),
                    value=json.dumps(message).encode("utf-8"),
                    callback=lambda err, msg, key=key: self._on_batch_delivery(err, msg, key, delivered),
                )
            except Exception as ex:  # pylint: disable=broad-exception-caught
                logger.error("key=%s error producing: %s", key, str(ex))
                continue
            producers_used[id(producer)] = producer

        for producer in producers_used.values():
            try:
                remaining = producer.flush(timeout=timeout)
            except Exception as ex:  # pylint: disable=broad-exception-caught
                logger.error("error flushing producer: %s", str(ex))
                continue
            if remaining > 0:
                logger.error("%s message(s) not delivered after flush timeout", remaining)

        # a copy, so a callback that fires after a timed-out flush cannot change what the caller got
        return set(delivered)

    @staticmethod
    def _instance_crn(payload) -> str | None:
        """The payload's data.instance_crn, or None when the payload is not shaped like one."""
        data = payload.get("data") if isinstance(payload, dict) else None
        return data.get("instance_crn") if isinstance(data, dict) else None

    def _on_batch_delivery(self, err, msg, key: int, delivered: set[int]) -> None:
        if err is None:
            delivered.add(key)
        else:
            self._log_delivery_error(err, msg)

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

    def send(self, payload: dict, timeout: float = 5) -> None:
        """Logs the payload instead of publishing it."""
        logger.info("payload=%s [noop] send", payload)


def build_kafka_sender() -> Sender:
    """Return a KafkaSender, or a NoOpSender when EVENT_STREAMS_ENABLED is false."""
    if settings.EVENT_STREAMS_ENABLED:
        logger.info("Initializing KafkaSender (EVENT_STREAMS_ENABLED=True)")
        return KafkaSender()
    logger.info("Initializing NoOpSender (EVENT_STREAMS_ENABLED=False)")
    return NoOpSender()
