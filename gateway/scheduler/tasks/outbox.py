"""Drain the outbox: send whatever each registered channel's messages need, independently, each
with its own circuit breaker and time budget, so a failure on one channel never stops another.
See specs/OUTBOX.md at the repository root for the full design. For the original design
rationale, if you have it locally, see .claude/specs/2026-09-25-generic-outbox-design.md
(local, not committed).
"""

import logging
import time
from dataclasses import dataclass

from django.utils import timezone

from core.config_key import ConfigKey
from core.ibm_cloud.event_streams.kafka_producers import UnroutableRegionError
from core.ibm_cloud.event_streams.kafka_sender import build_kafka_sender
from core.models import Config, Outbox, OutboxChannel

from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from .circuit_breaker import CircuitBreaker
from .task import SchedulerTask

logger = logging.getLogger("scheduler.OutboxTask")

BATCH_SIZE = 100


def _build_breaker() -> CircuitBreaker:
    """A fresh circuit breaker, its thresholds read lazily from Config so they can change at
    runtime without recreating the breaker or restarting the process."""
    return CircuitBreaker(
        failure_threshold=lambda: Config.get_int(ConfigKey.OUTBOX_BREAKER_FAILURES, default=5),
        pause_seconds=lambda: Config.get_int(ConfigKey.OUTBOX_BREAKER_PAUSE_SECONDS, default=60),
    )


@dataclass
class _Channel:
    """A registered outbox channel: its sender, its circuit breaker, and the Config key (if any)
    that enables it for both writing (Job._enqueue_billing_messages) and draining (below)."""

    sender: object
    breaker: CircuitBreaker
    enabled_key: ConfigKey | None = None

    @property
    def is_enabled(self) -> bool:
        """A channel with no enabled_key is always enabled."""
        return self.enabled_key is None or Config.get_bool(self.enabled_key)


class OutboxTask(SchedulerTask):
    """Send whatever every registered outbox channel owes. Messages are inserted in the Outbox table
    this class consumes this table and send and delete the message from the table using the right
    sender based on the channel."""

    def __init__(self, kill_signal: KillSignal, metrics: SchedulerMetrics):
        self.kill_signal = kill_signal
        self.metrics = metrics
        # LICENSE_FEE and USAGE share one sender, so they share this one breaker too: a Kafka
        # outage opens it once for both, instead of each channel counting its own failures
        # against the same underlying connection.
        billing_breaker = _build_breaker()
        billing_sender = build_kafka_sender()
        self.channels: dict[OutboxChannel, _Channel] = {
            OutboxChannel.LICENSE_FEE: _Channel(
                sender=billing_sender, breaker=billing_breaker, enabled_key=ConfigKey.OUTBOX_KAFKA_ENABLED
            ),
            OutboxChannel.JOB_USAGE: _Channel(
                sender=billing_sender, breaker=billing_breaker, enabled_key=ConfigKey.OUTBOX_KAFKA_ENABLED
            ),
        }

    def run(self):
        """Drain every enabled channel, in turn, each within its own breaker and budget. A
        disabled channel is skipped; the rest still drain."""
        for channel_name in self.channels:
            self._report_pending_gauges(channel_name)

        for channel_name, channel in self.channels.items():
            if not channel.is_enabled:
                continue
            self.metrics.set_outbox_breaker_open(channel.breaker.is_open, channel=channel_name)
            if channel.breaker.is_open:
                continue
            self._drain_channel(channel_name, channel.sender, channel.breaker)

    def _drain_channel(self, channel: OutboxChannel, sender, breaker: CircuitBreaker) -> None:
        # A row that fails without tripping the breaker is neither deleted nor blocked by the breaker, so an unfiltered
        # re-fetch would find the exact same row again and hot-loop on it for the rest of the budget window.
        budget_ms = Config.get_int(ConfigKey.OUTBOX_BUDGET_MS, default=500)
        deadline = time.monotonic() + (budget_ms / 1000)
        # So, tracking pks already attempted this call bounds one tick to at most one attempt per currently pending row;
        # it gets picked up again on the next tick.
        attempted_pks: set = set()

        while self._should_continue_draining(channel, breaker, deadline):
            queryset = Outbox.objects.filter(channel=channel).exclude(pk__in=attempted_pks)
            batch = list(queryset.order_by("created")[:BATCH_SIZE])
            if not batch:
                return

            for row in batch:
                if not self._should_continue_draining(channel, breaker, deadline):
                    return
                self._send_row(row, sender, breaker)
                attempted_pks.add(row.pk)

    def _should_continue_draining(self, channel: OutboxChannel, breaker: CircuitBreaker, deadline: float) -> bool:
        if self.kill_signal.received:
            logger.info("Kill signal received, stopping outbox drain for channel=%s", channel)
            return False
        if time.monotonic() >= deadline:
            logger.info("Time budget spent, stopping outbox drain for channel=%s this tick", channel)
            return False
        if breaker.is_open:
            logger.info("Circuit breaker opened, stopping outbox drain for channel=%s", channel)
            return False
        return True

    def _send_row(self, row: Outbox, sender, breaker: CircuitBreaker) -> None:
        """Send one row, keeping it for the next tick and counting it against the breaker on any
        failure, UnroutableRegionError included."""
        try:
            sender.send(row.payload)
        except UnroutableRegionError as ex:
            logger.error("outbox_id=%s job_id=%s error sending, unroutable CRN: %s", row.id, row.job_id, str(ex))
            self.metrics.increment_outbox_send(row.channel, "failure")
            breaker.record_failure()
            return
        except RuntimeError as ex:
            logger.error("outbox_id=%s job_id=%s error sending: %s", row.id, row.job_id, str(ex))
            self.metrics.increment_outbox_send(row.channel, "failure")
            breaker.record_failure()
            return

        self.metrics.increment_outbox_send(row.channel, "success")
        breaker.record_success()
        row.delete()

    def _report_pending_gauges(self, channel: OutboxChannel) -> None:
        queryset = Outbox.objects.filter(channel=channel)
        count = queryset.count()
        self.metrics.set_outbox_pending_rows(count, channel)
        oldest = queryset.order_by("created").first()
        age_seconds = (timezone.now() - oldest.created).total_seconds() if oldest else 0
        self.metrics.set_outbox_oldest_pending_age_seconds(age_seconds, channel)
