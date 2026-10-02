"""Drain the outbox: send whatever each registered channel's messages need, independently, each
with its own circuit breaker and time budget, so a failure on one channel never stops another.
See specs/OUTBOX.md at the repository root for the full design. For the original design
rationale, if you have it locally, see .claude/specs/2026-09-25-generic-outbox-design.md
(local, not committed).
"""

import logging

from core.config_key import ConfigKey
from core.ibm_cloud.event_streams.kafka_sender import build_kafka_sender
from core.models import Config, OutboxChannel

from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from .circuit_breaker import CircuitBreaker
from .outbox_destination import Destination
from .task import SchedulerTask

logger = logging.getLogger("scheduler.OutboxTask")


class OutboxTask(SchedulerTask):
    """Send whatever every registered outbox channel owes. Messages are inserted in the Outbox table
    and each channel drains its own rows, sending and deleting them with its sender."""

    def __init__(self, kill_signal: KillSignal, metrics: SchedulerMetrics):
        self.kill_signal = kill_signal
        self.metrics = metrics
        # LICENSE_FEE and USAGE share one destination, so they share its breakers too: a Kafka outage in a
        # region opens its breaker once for both, instead of each channel counting its own failures against
        # the same underlying connection.
        # The breaker thresholds are read lazily from Config, so they can change at runtime without recreating
        # the breakers or restarting the process.
        kafka = Destination(
            sender=build_kafka_sender(),
            breaker_factory=lambda: CircuitBreaker(
                failure_threshold=lambda: Config.get_int(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, default=5),
                pause_seconds=lambda: Config.get_int(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_PAUSE_SECONDS, default=60),
            ),
            budget_key=ConfigKey.OUTBOX_KAFKA_CHANNEL_BUDGET_MS,
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
            destination.report_gauges(channel_name)

        for channel_name, destination in self.channels.items():
            if self.kill_signal.received:
                logger.info("Kill signal received, stopping the outbox drain")
                return
            destination.drain(channel_name)
