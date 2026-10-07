"""Drain the outbox: send whatever each registered channel's messages need, independently, each
with its own circuit breaker and time budget, so a failure on one channel never stops another.
See specs/OUTBOX.md at the repository root for the full design. For the original design
rationale, if you have it locally, see .claude/specs/2026-09-25-generic-outbox-design.md
(local, not committed).
"""

import logging

from core.config_key import ConfigKey
from core.ibm_cloud.event_streams.kafka_sender import build_kafka_sender
from core.models import OutboxChannel

from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from .circuit_breaker import CircuitBreaker
from .outbox_destination import Destination
from .task import SchedulerTask

logger = logging.getLogger("scheduler.OutboxTask")


def build_kafka_circuit_breaker() -> CircuitBreaker:
    """A fresh circuit breaker for the Kafka channels, with the thresholds of their Config entries."""
    return CircuitBreaker(
        ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_PAUSE_SECONDS
    )


class OutboxTask(SchedulerTask):
    """Send whatever every registered outbox channel owes. Messages are inserted in the Outbox table
    and each channel drains its own rows, sending and deleting them with its sender."""

    def __init__(self, kill_signal: KillSignal, metrics: SchedulerMetrics):
        self.kill_signal = kill_signal
        self.metrics = metrics
        # LICENSE_FEE and JOB_USAGE share one destination, so they share its breakers too: a Kafka outage in a
        # region opens its breaker once for both, instead of each channel counting its own failures against
        # the same underlying connection.
        kafka = Destination(
            sender=build_kafka_sender(),
            breaker_factory=build_kafka_circuit_breaker,
            budget_key=ConfigKey.OUTBOX_KAFKA_CHANNEL_BUDGET_MS,
            retry_base_key=ConfigKey.OUTBOX_KAFKA_CHANNEL_RETRY_BASE_SECONDS,
            retry_max_key=ConfigKey.OUTBOX_KAFKA_CHANNEL_RETRY_MAX_SECONDS,
            metrics=metrics,
            kill_signal=kill_signal,
        )
        self.channels: dict[OutboxChannel, Destination] = {
            OutboxChannel.LICENSE_FEE: kafka,
            OutboxChannel.JOB_USAGE: kafka,
        }

    def run(self):
        """Drain every channel, in turn, each within its own breaker and budget."""
        for channel_name, destination in self.channels.items():
            destination.report_metrics(channel_name)

        for channel_name, destination in self.channels.items():
            if self.kill_signal.received:
                logger.info("Kill signal received, stopping the outbox drain")
                break
            destination.drain(channel_name)

        # Once every channel has drained, so the channels that share a destination report the same state, one
        # that a later channel opened during this very tick included.
        for channel_name, destination in self.channels.items():
            any_open = any(breaker.is_open for breaker in destination.breakers.values())
            self.metrics.set_outbox_breaker_open(any_open, channel=channel_name)
