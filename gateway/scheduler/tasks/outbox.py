"""Drain the outbox: send whatever each registered channel's messages need, independently, each
with its own circuit breaker and time budget, so a failure on one channel never stops another.
See specs/OUTBOX.md at the repository root for the full design. For the original design
rationale, if you have it locally, see .claude/specs/2026-09-25-generic-outbox-design.md
(local, not committed).
"""

import logging
import time
from dataclasses import dataclass
from typing import Callable

from django.utils import timezone

from core.config_key import ConfigKey
from core.ibm_cloud.sender import PendingMessage, Sender
from core.ibm_cloud.event_streams.kafka_sender import build_kafka_sender
from core.models import Config, Outbox, OutboxChannel

from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from .circuit_breaker import CircuitBreaker
from .task import SchedulerTask

logger = logging.getLogger("scheduler.OutboxTask")

BATCH_SIZE = 100


def _build_kafka_breaker() -> CircuitBreaker:
    """A fresh circuit breaker for the Kafka channels, its thresholds read lazily from Config so
    they can change at runtime without recreating the breaker or restarting the process."""
    return CircuitBreaker(
        failure_threshold=lambda: Config.get_int(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, default=5),
        pause_seconds=lambda: Config.get_int(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_PAUSE_SECONDS, default=60),
    )


class BreakerRegistry:
    """One circuit breaker per group key (a Kafka region, say), created on first use, so one failing
    destination opens only its own breaker."""

    def __init__(self, factory: Callable[[], CircuitBreaker]):
        self._factory = factory
        self._breakers: dict[str | None, CircuitBreaker] = {}

    def get(self, group_key: str | None) -> CircuitBreaker:
        """The breaker for this group, built the first time it is asked for."""
        if group_key not in self._breakers:
            self._breakers[group_key] = self._factory()
        return self._breakers[group_key]

    @property
    def any_open(self) -> bool:
        """Whether the breaker of at least one group is open."""
        return any(breaker.is_open for breaker in self._breakers.values())


class OutboxTask(SchedulerTask):
    """Send whatever every registered outbox channel owes. Messages are inserted in the Outbox table
    this class consumes this table and send and delete the message from the table using the right
    sender based on the channel."""

    @dataclass
    class Channel:
        """A registered outbox channel: its sender, its circuit breakers (one per sender group), and the
        Config key that holds its per-tick time budget in milliseconds."""

        sender: Sender
        breakers: BreakerRegistry
        budget_key: ConfigKey

    def __init__(self, kill_signal: KillSignal, metrics: SchedulerMetrics):
        self.kill_signal = kill_signal
        self.metrics = metrics
        # LICENSE_FEE and USAGE share one sender, so they share these breakers too: a Kafka
        # outage in a region opens its breaker once for both, instead of each channel counting its
        # own failures against the same underlying connection.
        billing_breakers = BreakerRegistry(_build_kafka_breaker)
        billing_sender = build_kafka_sender()
        self.channels: dict[OutboxChannel, OutboxTask.Channel] = {
            OutboxChannel.LICENSE_FEE: self.Channel(
                sender=billing_sender, breakers=billing_breakers, budget_key=ConfigKey.OUTBOX_KAFKA_CHANNEL_BUDGET_MS
            ),
            OutboxChannel.JOB_USAGE: self.Channel(
                sender=billing_sender, breakers=billing_breakers, budget_key=ConfigKey.OUTBOX_KAFKA_CHANNEL_BUDGET_MS
            ),
        }

    def run(self):
        """Drain every channel, in turn, each within its own breaker and budget."""
        for channel_name in self.channels:
            self._report_pending_gauges(channel_name)

        for channel_name, channel in self.channels.items():
            self.metrics.set_outbox_breaker_open(channel.breakers.any_open, channel=channel_name)
            self._drain_channel(channel_name, channel)

    def _drain_channel(self, channel_name: OutboxChannel, channel: Channel) -> None:
        # A row that fails without tripping the breaker is neither deleted nor blocked by the breaker, so an unfiltered
        # re-fetch would find the exact same row again and hot-loop on it for the rest of the budget window.
        budget_ms = Config.get_int(channel.budget_key, default=500)
        deadline = time.monotonic() + (budget_ms / 1000)
        # So, tracking pks already attempted this call bounds one tick to at most one attempt per currently pending row;
        # it gets picked up again on the next tick.
        attempted_pks: set = set()

        while self._should_continue_draining(channel_name, deadline):
            queryset = Outbox.objects.filter(channel=channel_name).exclude(pk__in=attempted_pks)
            batch = list(queryset.order_by("created")[:BATCH_SIZE])
            if not batch:
                return
            attempted_pks.update(row.pk for row in batch)

            # Each group (a Kafka region, say) has its own breaker, so a dead one is skipped while the
            # healthy ones keep draining. The budget is only for the healthy path: a group that fails
            # waits out its own flush timeout, which spends the budget and ends the tick.
            for group_key, rows in self._group_rows(batch, channel.sender).items():
                if not self._should_continue_draining(channel_name, deadline):
                    return
                breaker = channel.breakers.get(group_key)
                if breaker.is_open:
                    logger.info(
                        "Circuit breaker open, skipping %s row(s) for channel=%s group=%s",
                        len(rows),
                        channel_name,
                        group_key,
                    )
                    continue
                self._send_batch(rows, channel.sender, breaker)

    @staticmethod
    def _group_rows(batch: list[Outbox], sender: Sender) -> dict[str | None, list[Outbox]]:
        groups: dict[str | None, list[Outbox]] = {}
        for row in batch:
            groups.setdefault(sender.group_key(row.payload), []).append(row)
        return groups

    def _should_continue_draining(self, channel: OutboxChannel, deadline: float) -> bool:
        if self.kill_signal.received:
            logger.info("Kill signal received, stopping outbox drain for channel=%s", channel)
            return False
        if time.monotonic() >= deadline:
            logger.info("Time budget spent, stopping outbox drain for channel=%s this tick", channel)
            return False
        return True

    def _send_batch(self, batch: list[Outbox], sender: Sender, breaker: CircuitBreaker) -> None:
        """Send a batch with one confirmation round trip, delete the rows the sender confirmed and keep
        the rest for the next tick. The breaker records a success if at least one row was delivered
        and a failure only when none was, so a single bad row never opens it."""
        delivered = sender.send_batch([PendingMessage(row.pk, row.payload) for row in batch])

        for row in batch:
            self.metrics.increment_outbox_send(row.channel, "success" if row.pk in delivered else "failure")

        if len(delivered) < len(batch):
            logger.error(
                "outbox batch: %s of %s row(s) not delivered, kept for the next tick (the sender logged why)",
                len(batch) - len(delivered),
                len(batch),
            )

        if delivered:
            breaker.record_success()
            Outbox.objects.filter(pk__in=delivered).delete()
        else:
            breaker.record_failure()

    def _report_pending_gauges(self, channel: OutboxChannel) -> None:
        queryset = Outbox.objects.filter(channel=channel)
        count = queryset.count()
        self.metrics.set_outbox_pending_rows(count, channel)
        oldest = queryset.order_by("created").first()
        age_seconds = (timezone.now() - oldest.created).total_seconds() if oldest else 0
        self.metrics.set_outbox_oldest_pending_age_seconds(age_seconds, channel)
