"""Where outbox rows are sent: how its pending rows are found, sent and deleted. See specs/OUTBOX.md
at the repository root for the full design."""

import logging
import time
from typing import Callable

from django.db.models import Min, Q
from django.utils import timezone

from core.config_key import ConfigKey
from core.ibm_cloud.sender import PendingMessage, Sender
from core.models import Config, Outbox, OutboxChannel

from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from .circuit_breaker import CircuitBreaker

logger = logging.getLogger("scheduler.OutboxTask")

BATCH_SIZE = 100


class Destination:
    """Where outbox messages are delivered: the sender, its circuit breakers (one per region, built on demand
    with `breaker_factory`), and the Config key that holds the per-tick time budget in milliseconds. Several
    channels can share one destination, and then they share its breakers too: an outage in a region opens its
    breaker once for all of them. It knows how to drain the rows of any channel sent through it."""

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        sender: Sender,
        breaker_factory: Callable[[], CircuitBreaker],
        budget_key: ConfigKey,
        metrics: SchedulerMetrics,
        kill_signal: KillSignal,
    ):
        self.sender = sender
        self._breaker_factory = breaker_factory
        self._breakers: dict[str | None, CircuitBreaker] = {}
        self.budget_key = budget_key
        self.metrics = metrics
        self.kill_signal = kill_signal

    def breaker(self, region: str | None) -> CircuitBreaker:
        """The circuit breaker for this region (null included), built the first time it is asked for."""
        if region not in self._breakers:
            self._breakers[region] = self._breaker_factory()
        return self._breakers[region]

    def report_gauges(self, channel: OutboxChannel) -> None:
        """Report how many rows are pending and how long the oldest has been waiting."""
        queryset = Outbox.objects.filter(channel=channel)
        self.metrics.set_outbox_pending_rows(queryset.count(), channel)

        oldest = queryset.order_by("created").first()
        age_seconds = (timezone.now() - oldest.created).total_seconds() if oldest else 0
        self.metrics.set_outbox_oldest_pending_age_seconds(age_seconds, channel)

    def drain(self, channel: OutboxChannel) -> None:
        """Send the channel's pending rows within the time budget, region by region, and report whether any
        breaker is open once done, so it also reflects one that opened during this very tick."""
        budget_ms = Config.get_int(self.budget_key, default=500)
        self._drain_regions(channel, time.monotonic() + (budget_ms / 1000))
        any_open = any(breaker.is_open for breaker in self._breakers.values())
        self.metrics.set_outbox_breaker_open(any_open, channel=channel)

    def _drain_regions(self, channel: OutboxChannel, deadline: float) -> None:
        # Each region (null included) has its own breaker, so a dead one is skipped while the healthy ones
        # keep draining. The budget is only for the healthy path: a region that fails waits out its own
        # flush timeout, which spends the budget and ends the tick.
        for region in self._pending_regions(channel):
            if not self._should_continue_draining(channel, deadline):
                return
            if self.breaker(region).is_open:
                logger.info("Circuit breaker open, skipping channel=%s region=%s this tick", channel, region)
                continue
            self._drain_region(channel, region, deadline)

    def _pending_regions(self, channel: OutboxChannel) -> list[str | None]:
        """The regions (null included) that have pending rows, the one with the oldest row first."""
        pending = (
            Outbox.objects.filter(channel=channel)
            .values_list("region")
            .annotate(oldest=Min("created"))
            .order_by("oldest")
        )
        return [region for region, _ in pending]

    def _drain_region(self, channel: OutboxChannel, region: str | None, deadline: float) -> None:
        breaker = self.breaker(region)
        # A row that is not delivered stays in the table, so an unfiltered re-fetch would find the exact same
        # row again and hot-loop on it for the rest of the budget window. Paging forward from the last row
        # seen bounds one tick to at most one attempt per currently pending row; it gets picked up again on
        # the next tick.
        last_row: Outbox | None = None

        # The breaker is checked before every batch, so a failure that trips it keeps the rest of the
        # region's rows from being sent in this tick.
        while not breaker.is_open and self._should_continue_draining(channel, deadline):
            queryset = Outbox.objects.filter(channel=channel, region=region)
            if last_row is not None:
                queryset = queryset.filter(
                    Q(created__gt=last_row.created) | Q(created=last_row.created, pk__gt=last_row.pk)
                )
            batch = list(queryset.order_by("created", "pk")[:BATCH_SIZE])
            if not batch:
                return
            last_row = batch[-1]
            self._send_batch(batch, breaker)

    def _should_continue_draining(self, channel: OutboxChannel, deadline: float) -> bool:
        if self.kill_signal.received:
            logger.info("Kill signal received, stopping outbox drain for channel=%s", channel)
            return False
        if time.monotonic() >= deadline:
            logger.info("Time budget spent, stopping outbox drain for channel=%s this tick", channel)
            return False
        return True

    def _send_batch(self, batch: list[Outbox], breaker: CircuitBreaker) -> None:
        """Send a batch with one confirmation round trip, delete the rows the sender confirmed and keep
        the rest for the next tick. The breaker records a success if at least one row was delivered
        and a failure only when none was, so a single bad row never opens it."""
        delivered = self.sender.send_batch([PendingMessage(row.pk, row.payload) for row in batch])

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
