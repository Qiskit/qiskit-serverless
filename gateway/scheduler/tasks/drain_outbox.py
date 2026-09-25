"""Drain the outbox: send whatever each registered channel's messages need, independently, each
with its own circuit breaker and time budget, so a failure on one channel never stops another.
See .claude/specs/2026-09-25-generic-outbox-design.md (local, not committed).
"""

import logging
import time

from django.conf import settings
from django.utils import timezone

from core.config_key import ConfigKey
from core.ibm_cloud.event_streams.kafka_outbox_sender import KafkaOutboxSender, NoOpOutboxSender
from core.ibm_cloud.event_streams.kafka_producers import UnroutableRegionError
from core.models import Config, Outbox

from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from .circuit_breaker import CircuitBreaker
from .task import SchedulerTask

logger = logging.getLogger("scheduler.DrainOutbox")

BATCH_SIZE = 100


class DrainOutbox(SchedulerTask):
    """Send whatever every registered outbox channel owes. Adding a channel (the PR2 "workload"
    mirror) is adding one entry to `senders`; nothing else here changes."""

    def __init__(self, kill_signal: KillSignal, metrics: SchedulerMetrics):
        self.kill_signal = kill_signal
        self.metrics = metrics
        self._senders: dict[str, object] | None = None
        self._breakers: dict[str, CircuitBreaker] = {}

    @property
    def senders(self) -> dict[str, object]:
        """The registered {channel: sender}, built lazily on first access."""
        if self._senders is None:
            if settings.EVENT_STREAMS_ENABLED:
                logger.info("Initializing KafkaOutboxSender (EVENT_STREAMS_ENABLED=True)")
                billing_sender = KafkaOutboxSender()
            else:
                logger.info("Initializing NoOpOutboxSender (EVENT_STREAMS_ENABLED=False)")
                billing_sender = NoOpOutboxSender()
            self._senders = {"billing": billing_sender}
        return self._senders

    def _breaker_for(self, channel: str) -> CircuitBreaker:
        if channel not in self._breakers:
            self._breakers[channel] = CircuitBreaker(
                failure_threshold=lambda: Config.get_int(ConfigKey.OUTBOX_BREAKER_FAILURES, default=5),
                pause_seconds=lambda: Config.get_int(ConfigKey.OUTBOX_BREAKER_PAUSE_SECONDS, default=60),
            )
        return self._breakers[channel]

    def run(self):
        """Drain every registered channel, in turn, each within its own breaker and budget."""
        if not Config.get_bool(ConfigKey.OUTBOX_ENABLED):
            return

        for channel in self.senders:
            self._report_pending_gauges(channel)

        for channel, sender in self.senders.items():
            breaker = self._breaker_for(channel)
            self.metrics.set_outbox_breaker_open(breaker.is_open, channel=channel)
            if breaker.is_open:
                continue
            self._drain_channel(channel, sender, breaker)

    def _drain_channel(self, channel: str, sender, breaker: CircuitBreaker) -> None:
        budget_ms = Config.get_int(ConfigKey.OUTBOX_BUDGET_MS, default=500)
        deadline = time.monotonic() + (budget_ms / 1000)
        # A row that fails without tripping the breaker (RuntimeError) or that is unroutable
        # is neither deleted nor blocked by the breaker, so an unfiltered re-fetch would find
        # the exact same row again and hot-loop on it for the rest of the budget window.
        # Tracking pks already attempted this call bounds one tick to at most one attempt per
        # currently pending row; it gets picked up again on the next tick.
        attempted_pks: set = set()

        while True:
            if self._should_stop_draining(channel, breaker, deadline):
                return

            queryset = Outbox.objects.filter(channel=channel)
            if attempted_pks:
                queryset = queryset.exclude(pk__in=attempted_pks)
            batch = list(queryset.order_by("created")[:BATCH_SIZE])
            if not batch:
                return

            for row in batch:
                if self._should_stop_draining(channel, breaker, deadline):
                    return
                self._send_row(row, sender, breaker)
                attempted_pks.add(row.pk)

    def _should_stop_draining(self, channel: str, breaker: CircuitBreaker, deadline: float) -> bool:
        if self.kill_signal.received:
            logger.info("Kill signal received, stopping outbox drain for channel=%s", channel)
            return True
        if time.monotonic() >= deadline:
            logger.info("Time budget spent, stopping outbox drain for channel=%s this tick", channel)
            return True
        if breaker.is_open:
            logger.info("Circuit breaker opened, stopping outbox drain for channel=%s", channel)
            return True
        return False

    def _send_row(self, row: Outbox, sender, breaker: CircuitBreaker) -> None:
        """fact is billing-specific vocabulary (license_fee vs billing_event), read from the
        payload for metrics only. A future non-billing channel either reports no fact split, or
        gets its own if-branch here; nothing about delivery depends on it."""
        fact = self._fact_label(row.payload)
        try:
            sender.send(row.payload)
        except UnroutableRegionError as ex:
            logger.error("outbox_id=%s job_id=%s unroutable, will retry: %s", row.id, row.job_id, str(ex))
            self.metrics.increment_outbox_send(fact, "unroutable")
            return
        except RuntimeError as ex:
            logger.error("outbox_id=%s job_id=%s error sending: %s", row.id, row.job_id, str(ex))
            self.metrics.increment_outbox_send(fact, "failure")
            breaker.record_failure()
            return

        self.metrics.increment_outbox_send(fact, "success")
        breaker.record_success()
        row.delete()

    @staticmethod
    def _fact_label(payload: dict) -> str:
        metric_type = payload.get("data", {}).get("metric_type", "")
        return "license_fee" if metric_type.startswith("license") else "billing_event"

    def _report_pending_gauges(self, channel: str) -> None:
        """Same billing-specific caveat as _fact_label: only "billing" gets the finer fact
        breakdown, everything else reports one count for the whole channel."""
        now = timezone.now()
        if channel == "billing":
            for fact, metric_type_prefix in (("license_fee", "license"), ("billing_event", "classical")):
                queryset = Outbox.objects.filter(
                    channel=channel, payload__data__metric_type__startswith=metric_type_prefix
                )
                self._report_gauge_for(queryset, fact, now)
        else:
            self._report_gauge_for(Outbox.objects.filter(channel=channel), channel, now)

    def _report_gauge_for(self, queryset, label: str, now) -> None:
        count = queryset.count()
        self.metrics.set_outbox_pending_rows(count, label)
        oldest = queryset.order_by("created").first()
        age_seconds = (now - oldest.created).total_seconds() if oldest else 0
        self.metrics.set_outbox_oldest_pending_age_seconds(age_seconds, label)
