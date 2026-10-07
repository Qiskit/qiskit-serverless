"""Where outbox rows are sent: how its pending rows are found, sent and deleted. See specs/OUTBOX.md
at the repository root for the full design."""

import logging
import time
from datetime import timedelta
from typing import Callable

from django.db.models import Min
from django.utils import timezone

from core.config_key import ConfigKey
from core.ibm_cloud.sender import BatchSender, PendingMessage, Sender
from core.models import Config, Outbox, OutboxChannel

from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from .circuit_breaker import CircuitBreaker

logger = logging.getLogger("scheduler.OutboxTask")

BATCH_SIZE = 100
LAST_ERROR_MAX_LENGTH = 500  # the size of Outbox.last_error
MIN_RETRY_WAIT_SECONDS = 1  # so a failed row is never due again within the same tick
MAX_RETRY_DOUBLINGS = 30  # an attempts count that keeps growing must not build a huge number
MAX_RETRY_WAIT_SECONDS = 24 * 3600  # whatever the Config entries say, so a typo cannot overflow a timedelta


class Destination:
    """Where outbox messages are delivered: the sender, its circuit breakers (one per region, built on demand
    with `breaker_factory`), the Config key that holds the per-tick time budget in milliseconds, and the two that
    set how long a row that failed waits before its next try (`retry_base_key` and `retry_max_key`). Several
    channels can share one destination, and then they share its breakers too: an outage in a region opens its
    breaker once for all of them. It knows how to drain the rows of any channel sent through it."""

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        sender: Sender,
        breaker_factory: Callable[[], CircuitBreaker],
        budget_key: ConfigKey,
        retry_base_key: ConfigKey,
        retry_max_key: ConfigKey,
        metrics: SchedulerMetrics,
        kill_signal: KillSignal,
    ):
        self.sender = sender
        self._breaker_factory = breaker_factory
        self.breakers: dict[str | None, CircuitBreaker] = {}
        self.budget_key = budget_key
        self.retry_base_key = retry_base_key
        self.retry_max_key = retry_max_key
        self.metrics = metrics
        self.kill_signal = kill_signal

    def get_breaker(self, region: str | None) -> CircuitBreaker:
        """The circuit breaker for this region (null included), built the first time it is asked for."""
        if region not in self.breakers:
            self.breakers[region] = self._breaker_factory()
        return self.breakers[region]

    def report_metrics(self, channel: OutboxChannel) -> None:
        """Report how many rows are pending and how long the oldest has been waiting."""
        queryset = Outbox.objects.filter(channel=channel)
        self.metrics.set_outbox_pending_rows(queryset.count(), channel)

        oldest = queryset.order_by("created").first()
        age_seconds = (timezone.now() - oldest.created).total_seconds() if oldest else 0
        self.metrics.set_outbox_oldest_pending_age_seconds(age_seconds, channel)

    def drain(self, channel: OutboxChannel) -> None:
        """Send the channel's pending rows within the time budget, region by region."""
        budget_ms = Config.get_int(self.budget_key, default=500)
        deadline = time.monotonic() + (budget_ms / 1000)

        # Each region (null included) has its own breaker, so a dead one is skipped while the healthy ones
        # keep draining. The budget is only for the healthy path: a region that fails waits out its own
        # flush timeout, which spends the budget and ends the tick.
        for region in self._pending_regions(channel):
            if not self._should_continue_draining(channel, deadline):
                return
            if self.get_breaker(region).is_open:
                logger.info("Circuit breaker open, skipping channel=%s region=%s this tick", channel, region)
                continue
            self._drain_region(channel, region, deadline)

    def _pending_regions(self, channel: OutboxChannel) -> list[str | None]:
        """The regions (null included) that have rows due to be sent, the one with the oldest row first."""
        pending = (
            Outbox.objects.filter(channel=channel, next_attempt_at__lte=timezone.now())
            .values_list("region")
            .annotate(oldest=Min("created"))
            .order_by("oldest")
        )
        return [region for region, _ in pending]

    def _drain_region(self, channel: OutboxChannel, region: str | None, deadline: float) -> None:
        breaker = self.get_breaker(region)

        # The breaker is checked before every batch, so a failure that trips it keeps the rest of the
        # region's rows from being sent in this tick. A row that fails is not due again for at least a second
        # (see _keep_for_retry), so the next fetch cannot find it and one tick makes at most one attempt per
        # row that is due.
        while not breaker.is_open and self._should_continue_draining(channel, deadline):
            # Rows that never failed go first, then the oldest of the rest. A pile of rows that always fail
            # (each due again after its wait) can then never be what a whole batch is made of, and keep the
            # breaker from closing on a success, while a fresh row is waiting behind it.
            batch = list(
                Outbox.objects.filter(channel=channel, region=region, next_attempt_at__lte=timezone.now()).order_by(
                    "attempts", "created", "pk"
                )[:BATCH_SIZE]
            )
            if not batch:
                return
            if isinstance(self.sender, BatchSender):
                self._send_batch(self.sender, batch, breaker)
            else:
                self._send_one_by_one(channel, batch, breaker, deadline)

    def _should_continue_draining(self, channel: OutboxChannel, deadline: float) -> bool:
        if self.kill_signal.received:
            logger.info("Kill signal received, stopping outbox drain for channel=%s", channel)
            return False
        if time.monotonic() >= deadline:
            logger.info("Time budget spent, stopping outbox drain for channel=%s this tick", channel)
            return False
        return True

    def _send_batch(self, sender: BatchSender, batch: list[Outbox], breaker: CircuitBreaker) -> None:
        """Send a batch with one confirmation round trip, delete the rows the sender confirmed and put the
        rest into a wait before their next try. The breaker records a success if at least one row was delivered
        and a failure only when none was, so a single bad row never opens it."""
        pending_messages = [PendingMessage(row.pk, row.payload) for row in batch]
        delivered = sender.send_batch(pending_messages)

        for row in batch:
            self.metrics.increment_outbox_send(row.channel, "success" if row.pk in delivered else "failure")

        if len(delivered) < len(batch):
            logger.error(
                "outbox batch: %s of %s row(s) not delivered, kept to try again later (the sender logged why)",
                len(batch) - len(delivered),
                len(batch),
            )

        # What the sender did is recorded first, so a failure to write the retry state below cannot make the
        # rows it delivered be sent again or leave the breaker without its count.
        if delivered:
            breaker.record_success()
            Outbox.objects.filter(pk__in=delivered).delete()
        else:
            breaker.record_failure()
        self._keep_for_retry([row for row in batch if row.pk not in delivered], "not confirmed by the sender")

    def _send_one_by_one(
        self, channel: OutboxChannel, batch: list[Outbox], breaker: CircuitBreaker, deadline: float
    ) -> None:
        """Send the rows one at a time, deleting each one as soon as it is delivered. Every failure counts
        against the breaker right away, and once it opens the rest of the batch is left untouched, like the
        rows the budget or a kill signal cut off."""
        for row in batch:
            if breaker.is_open or not self._should_continue_draining(channel, deadline):
                return
            try:
                self.sender.send(row.payload)
            except Exception as ex:  # pylint: disable=broad-exception-caught
                logger.error(
                    "outbox_id=%s job_id=%s error sending, kept to try again later: %s", row.id, row.job_id, ex
                )
                self.metrics.increment_outbox_send(row.channel, "failure")
                breaker.record_failure()
                self._keep_for_retry([row], f"{type(ex).__name__}: {ex}")
                continue
            self.metrics.increment_outbox_send(row.channel, "success")
            breaker.record_success()
            row.delete()

    def _keep_for_retry(self, rows: list[Outbox], error: str) -> None:
        """Record a failed attempt on each row and move its next try further away: the wait is the base of the
        Config entry doubled for every attempt so far, up to the cap, and never less than a second. Until then
        the drain does not read the row, so a row that always fails stops being the one tried first."""
        if not rows:
            return
        base = Config.get_int(self.retry_base_key, default=120)
        cap = Config.get_int(self.retry_max_key, default=600)
        now = timezone.now()
        # a NUL character is not allowed in a PostgreSQL text column, and an exception message can carry one
        error = error.replace("\x00", "")[:LAST_ERROR_MAX_LENGTH]
        for row in rows:
            row.attempts += 1
            row.last_error = error
            wait = base * 2 ** min(row.attempts - 1, MAX_RETRY_DOUBLINGS)
            wait = min(wait, cap, MAX_RETRY_WAIT_SECONDS)
            row.next_attempt_at = now + timedelta(seconds=max(MIN_RETRY_WAIT_SECONDS, wait))
        Outbox.objects.bulk_update(rows, ["attempts", "last_error", "next_attempt_at"])
