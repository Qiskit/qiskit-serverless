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

"""Kafka consumer for every configured region's Event Streams bus, driven by a scheduler task
(see scheduler/tasks/consume_blocked_account_events.py).

The scheduler is single-threaded, so drain() never waits on the broker: it takes whatever each
region already has in its local queue (consume() with a zero timeout), hands each message to the
injected handler, commits what it finished asynchronously, and returns within the tick. librdkafka
keeps fetching, heartbeating and committing in its own background threads between ticks.

Delivery is at-least-once, so handlers must be idempotent:
- a message is committed once it is done: handled, a tombstone, or impossible to handle (a payload
  that is not a JSON object, or a handler raising InvalidEventError). Committing over the last ones
  keeps one bad payload from stalling its partition forever.
- any other handler failure is taken as transient: the partition is rewound to the failed message,
  nothing from it on is committed, and the failure is re-raised once every region has been drained,
  so the scheduler loop records it. The message is retried next tick.
- a message left unprocessed because of the kill signal is not committed either: whoever owns the
  partition next starts from it.

The regions and their credentials come from regions.region_configs(), the same as KafkaProducers.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

from confluent_kafka import Consumer, KafkaError, KafkaException, Message, TopicPartition

from .regions import region_configs, sasl_config

logger = logging.getLogger("gateway.ibm_cloud.event_streams_consumer")

# Most messages one region may contribute to a single scheduler tick, so a backlog is drained
# over several ticks rather than holding the loop inside one of them.
MAX_MESSAGES_PER_REGION_PER_TICK = 100

# DrainStats outcomes
HANDLED = "handled"
INVALID = "invalid"
TOMBSTONE = "tombstone"
RETRY = "retry"
CONSUMER_ERROR = "consumer_error"
COMMIT_ERROR = "commit_error"
FATAL = "fatal"

# (payload, key, region)
EventHandler = Callable[[dict, str | None, str], None]


class InvalidEventError(Exception):
    """Raised by a handler for an event it can never handle, however often it is retried. The
    message is committed over instead of retried."""


@dataclass
class DrainStats:
    """What a drain() did, counted per (region, outcome), for the caller to turn into metrics."""

    counts: Counter = field(default_factory=Counter)

    def add(self, region: str, outcome: str) -> None:
        """Count one outcome for region."""
        self.counts[(region, outcome)] += 1


class KafkaRegionalConsumer:
    """Consumes topics from every configured region's Kafka bus, one consumer per region, and
    hands each event to handler."""

    def __init__(self, topics: list[str], group_id: str, handler: EventHandler) -> None:
        self.topics = topics
        self.group_id = group_id
        self._handler = handler
        self._region_configs = region_configs()
        self._consumers: dict[str, Consumer] = {}
        # Regions whose consumer reported a fatal error: it can no longer be used, so it is
        # rebuilt at the start of the region's next drain.
        self._fatal_regions: set[str] = set()
        # Regions whose consumer could not be built last time, so a broken config logs its
        # traceback once per streak rather than every tick.
        self._failing_regions: set[str] = set()
        # The stats of the drain in progress, for the callbacks librdkafka serves inside consume().
        self._stats = DrainStats()

        logger.info(
            "Initialized consumer: group=%s topics=%s regions=%s",
            group_id,
            ",".join(topics),
            sorted(self._region_configs.keys()),
        )

    def drain(self, should_stop: Callable[[], bool], stats: DrainStats) -> None:
        """Handle whatever every region has queued, up to MAX_MESSAGES_PER_REGION_PER_TICK each,
        counting what happened into stats.

        Raises:
            Exception: the first transient handler failure, once every region has been drained.
        """
        self._stats = stats
        failure: Exception | None = None
        try:
            for region in self._region_configs:
                if should_stop():
                    logger.info("Kill signal received, stopping the drain: group=%s", self.group_id)
                    break
                region_failure = self._drain_region(region, should_stop)
                failure = failure or region_failure
        finally:
            self._stats = DrainStats()

        if failure is not None:
            raise failure

    def close(self) -> None:
        """Close every region's consumer, so each leaves the group now instead of holding its
        partitions until its session times out. Blocks while they leave: meant for shutdown."""
        for region in list(self._consumers):
            self._discard_consumer(region)

    def _drain_region(self, region: str, should_stop: Callable[[], bool]) -> Exception | None:
        """Handle one region's queued messages and commit the ones it finished. Returns the
        transient handler failure that cut the batch short, if any."""
        if region in self._fatal_regions:
            self._fatal_regions.discard(region)
            self._discard_consumer(region)

        consumer = self._get_consumer(region)
        if consumer is None:
            return None

        try:
            messages = consumer.consume(num_messages=MAX_MESSAGES_PER_REGION_PER_TICK, timeout=0)
        except KafkaException as e:
            self._on_kafka_exception(region, e)
            return None

        # Next offset to commit, per (topic, partition), for the messages this batch finished
        done: dict[tuple[str, int], int] = {}
        failure: Exception | None = None
        for index, msg in enumerate(messages):
            if should_stop():
                logger.info("Kill signal received, leaving the rest of region=%s uncommitted", region)
                break

            error = msg.error()
            if error is not None:
                self._on_kafka_error(region, error)
                if error.fatal():
                    break
                continue

            try:
                self._handle(msg, region)
            except Exception as e:  # pylint: disable=broad-exception-caught
                self._stats.add(region, RETRY)
                logger.error(
                    "Failed to handle event, retrying next tick: region=%s topic=%s partition=%s offset=%s error=%s",
                    region,
                    msg.topic(),
                    msg.partition(),
                    msg.offset(),
                    str(e),
                )
                self._rewind(consumer, region, messages[index:])
                failure = e
                break

            done[(msg.topic(), msg.partition())] = msg.offset() + 1

        self._commit(consumer, region, done)
        return failure

    def _handle(self, msg: Message, region: str) -> None:
        """Hand one message to the handler. An event that can never be handled is logged and
        counted, not raised; any other failure of the handler is raised."""
        key = msg.key().decode("utf-8", errors="replace") if msg.key() is not None else None
        value = msg.value()
        if value is None:
            # A tombstone: the key's previous event is deleted from a compacted topic
            self._stats.add(region, TOMBSTONE)
            logger.info("Tombstone: region=%s topic=%s key=%s", region, msg.topic(), key)
            return

        try:
            payload = self._deserialize(value)
            self._handler(payload, key, region)
        except InvalidEventError as e:
            self._stats.add(region, INVALID)
            logger.error(
                "Invalid event, skipping it: region=%s topic=%s partition=%s offset=%s error=%s",
                region,
                msg.topic(),
                msg.partition(),
                msg.offset(),
                str(e),
            )
            return

        self._stats.add(region, HANDLED)

    @staticmethod
    def _deserialize(value: bytes) -> dict:
        """Parse a JSON object payload, or raise InvalidEventError."""
        try:
            payload = json.loads(value)
        except ValueError as e:  # JSONDecodeError and UnicodeDecodeError are both ValueErrors
            raise InvalidEventError(f"payload is not valid JSON: {e}") from e
        if not isinstance(payload, dict):
            raise InvalidEventError(f"payload is a JSON {type(payload).__name__}, not an object")
        return payload

    def _rewind(self, consumer: Consumer, region: str, remaining: list[Message]) -> None:
        """Seek every partition in remaining back to its first message there, so they are all
        fetched again next tick."""
        first_offsets: dict[tuple[str, int], int] = {}
        for msg in remaining:
            if msg.error() is None:
                first_offsets.setdefault((msg.topic(), msg.partition()), msg.offset())

        for (topic, partition), offset in first_offsets.items():
            try:
                consumer.seek(TopicPartition(topic, partition, offset))
            except KafkaException as e:
                # Typically the partition was just revoked: its next owner resumes from the last commit
                logger.warning(
                    "Could not rewind: region=%s topic=%s partition=%s offset=%s error=%s",
                    region,
                    topic,
                    partition,
                    offset,
                    str(e),
                )

    def _commit(self, consumer: Consumer, region: str, done: dict[tuple[str, int], int]) -> None:
        """Commit the finished offsets, asynchronously, so the tick never waits on the broker. A
        commit that fails is reported through on_commit, and its messages are delivered again."""
        if not done:
            return
        offsets = [TopicPartition(topic, partition, offset) for (topic, partition), offset in done.items()]
        try:
            consumer.commit(offsets=offsets, asynchronous=True)
        except KafkaException as e:
            self._stats.add(region, COMMIT_ERROR)
            logger.warning("Commit failed: region=%s error=%s", region, str(e))

    def _on_commit(self, region: str, error: KafkaError | None, partitions: list[TopicPartition]) -> None:
        """librdkafka's on_commit callback, served inside consume()."""
        failed = [tp for tp in partitions if tp.error is not None]
        if error is None and not failed:
            return
        self._stats.add(region, COMMIT_ERROR)
        logger.warning("Commit failed: region=%s error=%s partitions=%s", region, error, failed)

    def _on_kafka_exception(self, region: str, exception: KafkaException) -> None:
        """A KafkaException raised by the consumer, handled as the KafkaError it carries."""
        error = exception.args[0] if exception.args and isinstance(exception.args[0], KafkaError) else None
        if error is not None:
            self._on_kafka_error(region, error)
            return
        self._stats.add(region, CONSUMER_ERROR)
        logger.warning("Consumer error: region=%s error=%s", region, str(exception))

    def _on_kafka_error(self, region: str, error: KafkaError) -> None:
        """An error from the consumer, either as librdkafka's error_cb or carried by a message.

        librdkafka recovers on its own from anything but a fatal error, so only a fatal one has the
        consumer rebuilt; rebuilding it for the others would only rejoin the group, and rebalance it,
        for nothing.
        """
        if error.fatal():
            self._stats.add(region, FATAL)
            self._fatal_regions.add(region)
            logger.error("Fatal consumer error, rebuilding the consumer next tick: region=%s error=%s", region, error)
            return
        self._stats.add(region, CONSUMER_ERROR)
        logger.warning("Consumer error: region=%s error=%s", region, error)

    def _get_consumer(self, region: str) -> Consumer | None:
        """Get or create the consumer for region, or None if it cannot be created. One per region,
        cached, so successive ticks reuse the same group member instead of joining the group again."""
        consumer = self._consumers.get(region)
        if consumer is not None:
            return consumer

        consumer = None
        try:
            consumer = Consumer(self._consumer_config(region))
            consumer.subscribe(self.topics)
        except Exception as e:  # pylint: disable=broad-exception-caught
            self._stats.add(region, CONSUMER_ERROR)
            first_error = region not in self._failing_regions
            self._failing_regions.add(region)
            logger.error("Could not create consumer: region=%s error=%s", region, str(e), exc_info=first_error)
            if consumer is not None:
                self._close_quietly(region, consumer)
            return None

        self._failing_regions.discard(region)
        self._consumers[region] = consumer
        logger.debug("Created consumer: region=%s topics=%s", region, ",".join(self.topics))
        return consumer

    def _consumer_config(self, region: str) -> dict:
        """The librdkafka configuration of region's consumer."""
        return {
            **sasl_config(self._region_configs[region]),
            "group.id": self.group_id,
            "enable.auto.commit": False,
            # A group with no committed offsets yet, i.e. its first deployment, starts from the oldest
            # retained message: these topics describe state, so what happened before the group existed
            # still matters. Expect a catch-up, paced by MAX_MESSAGES_PER_REGION_PER_TICK.
            "auto.offset.reset": "earliest",
            # max.poll.interval.ms keeps its default of 5 min: a scheduler tick longer than that makes
            # the consumer leave the group, and the next consume() rejoins it.
            "error_cb": lambda error: self._on_kafka_error(region, error),
            "on_commit": lambda error, partitions: self._on_commit(region, error, partitions),
        }

    def _discard_consumer(self, region: str) -> None:
        """Close and forget a region's consumer."""
        consumer = self._consumers.pop(region, None)
        if consumer is not None:
            self._close_quietly(region, consumer)

    @staticmethod
    def _close_quietly(region: str, consumer: Consumer) -> None:
        """Close a consumer. Closing matters: leaving it open would keep a zombie member in the
        group, still holding the partitions its replacement needs."""
        try:
            consumer.close()
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to close consumer: region=%s error=%s", region, str(e))
