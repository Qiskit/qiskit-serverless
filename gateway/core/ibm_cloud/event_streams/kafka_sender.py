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
    sender.send(payload, timeout=0)  # does not wait for the broker and never raises: a failure is only logged

The outbox uses sender.send_batch(messages) instead, which never raises and returns the keys the broker
confirmed.

See outbox.py and core/services/job_transitions.py for the two real callers.
"""

import json
import logging
import time
from collections.abc import Callable

from confluent_kafka import Producer
from django.conf import settings

from core.ibm_cloud.sender import PendingMessage, Sender
from .kafka_producers import KafkaProducers, UnroutableRegionError

logger = logging.getLogger("gateway.ibm_cloud.event_streams_client")


class KafkaSender(Sender):
    """Sends a payload to Kafka as-is, plus `type`. See KafkaProducers for how producers/topic
    are configured and how a payload's CRN is routed to a region."""

    def __init__(self, producers: KafkaProducers | None = None, clock: Callable[[], float] = time.monotonic) -> None:
        self._producers = producers or KafkaProducers()
        self._clock = clock
        self._dropped = 0  # best effort messages lost since the last warning
        self._last_drop_warning = float("-inf")

    def send(self, payload: dict, timeout: float = 5) -> None:
        """Raises UnroutableRegionError (from KafkaProducers.get) or RuntimeError on failure.

        With timeout=0 it does not wait for the broker and never raises: see _send_without_waiting."""
        if timeout == 0:
            self._send_without_waiting(payload)
            return

        # flush() returning 0 only means nothing is left outstanding, not that delivery succeeded:
        # a fast broker-side rejection (e.g. a topic ACL problem) calls the callback with an error
        # before flush() returns, so the callback has to record it for us to raise below.
        delivery_errors = []

        def on_delivery(err, msg):
            if err is not None:
                self._log_delivery_error(err, msg)
                delivery_errors.append(err)

        try:
            producer = self._produce(payload, on_delivery)
            remaining = producer.flush(timeout=timeout)
            if remaining > 0:
                raise RuntimeError(f"KafkaSender: {remaining} message(s) not delivered after flush timeout")
            if delivery_errors:
                raise RuntimeError(f"KafkaSender: message delivery failed: {delivery_errors[0]}")
        except UnroutableRegionError:
            # no data.instance_crn (impossible), an invalid crn (even more impossible), or no producer for its region
            raise
        except Exception as e:
            event_id = payload.get("id") if isinstance(payload, dict) else None
            raise RuntimeError(f"KafkaSender: Failed to publish event (id={event_id}): {str(e)}") from e

    def _produce(self, payload: dict, callback) -> Producer:
        """Queue the payload, plus `type`, in its region's producer and return that producer. Does not wait.
        Raises UnroutableRegionError when it cannot be routed, or whatever produce() raises (a full queue)."""
        message = {**payload, "type": self._producers.topic}
        producer = self._producers.get(self._instance_crn(message))
        try:
            producer.produce(
                topic=self._producers.topic,
                key=message["subject"].encode("utf-8"),
                value=json.dumps(message).encode("utf-8"),
                callback=callback,
            )
        except BufferError:
            # The local queue also holds the messages already delivered or expired, until their delivery report
            # is served. Only poll() serves them, so without it a full queue would never be emptied.
            producer.poll(0)
            raise
        return producer

    def _send_without_waiting(self, payload: dict) -> None:
        """Queue the message and return: the producer delivers it in the background and gives up on it after
        message.timeout.ms. poll(0) serves the delivery reports of earlier messages."""
        subject = payload.get("subject") if isinstance(payload, dict) else None

        def on_delivery(err, _msg):
            if err is not None:
                self._drop(subject, err)

        try:
            self._produce(payload, on_delivery).poll(0)
        except Exception as ex:  # pylint: disable=broad-exception-caught
            self._drop(subject, ex)

    def _drop(self, subject: str | None, error) -> None:
        """A best effort message was lost. Warn at most once per 30 s, with how many were lost since the last
        warning, so a broker that is down does not write a log line per job per second."""
        self._dropped += 1
        now = self._clock()
        if now - self._last_drop_warning >= 30:
            logger.warning(
                "%s best effort message(s) dropped since the last warning, last: subject=%s error=%s",
                self._dropped,
                subject,
                error,
            )
            self._dropped, self._last_drop_warning = 0, now

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
                producer = self._produce(
                    pending.payload, lambda err, msg, key=key: self._on_batch_delivery(err, msg, key, delivered)
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
