"""Drain the outbox's two Kafka billing facts: the license fee and the final usage event.

See .claude/specs/2026-09-16-job-outbox-design.md, sections 9 and 9.1.
"""

import logging
import time
from datetime import datetime

from django.conf import settings
from django.utils import timezone

from core.config_key import ConfigKey
from core.ibm_cloud.event_streams.abstract_event_streams_client import EventStreamsClient
from core.ibm_cloud.event_streams.kafka_event_streams_client import KafkaEventStreamsClient
from core.ibm_cloud.event_streams.noop_event_streams_client import NoOpEventStreamsClient
from core.models import Config, JobOutbox

from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from .circuit_breaker import CircuitBreaker
from .task import SchedulerTask

logger = logging.getLogger("scheduler.PublishOutbox")

FACT_LICENSE_FEE = "license_fee"
FACT_BILLING_EVENT = "billing_event"

BATCH_SIZE = 100


class PublishOutbox(SchedulerTask):
    """Send the license fee and the final usage event for terminal Fleets jobs."""

    def __init__(self, kill_signal: KillSignal, metrics: SchedulerMetrics):
        self.kill_signal = kill_signal
        self.metrics = metrics
        self._event_streams_client: EventStreamsClient | None = None
        self._breaker = CircuitBreaker(
            failure_threshold=Config.get_int(ConfigKey.OUTBOX_BREAKER_FAILURES, default=5),
            pause_seconds=Config.get_int(ConfigKey.OUTBOX_BREAKER_PAUSE_SECONDS, default=60),
        )

    @property
    def event_streams_client(self) -> EventStreamsClient:
        """Return the Event Streams client, instantiating it lazily on first access."""
        if self._event_streams_client is None:
            if settings.EVENT_STREAMS_ENABLED:
                logger.info("Initializing KafkaEventStreamsClient (EVENT_STREAMS_ENABLED=True)")
                self._event_streams_client = KafkaEventStreamsClient()
            else:
                logger.info("Initializing NoOpEventStreamsClient (EVENT_STREAMS_ENABLED=False)")
                self._event_streams_client = NoOpEventStreamsClient()
        return self._event_streams_client

    def run(self):
        """Drain outbox rows in successive small batches, until either nothing is left to
        send or the time budget for this tick runs out."""
        if not Config.get_bool(ConfigKey.OUTBOX_ENABLED):
            return

        self.metrics.set_outbox_breaker_open(self._breaker.is_open)
        self._report_pending_gauges()

        if self._breaker.is_open:
            return

        budget_ms = Config.get_int(ConfigKey.OUTBOX_BUDGET_MS, default=500)
        deadline = time.monotonic() + (budget_ms / 1000)

        while True:
            if time.monotonic() >= deadline:
                logger.info("Time budget spent, stopping outbox drain for this tick")
                return

            batch = self._fetch_batch()
            if not batch:
                return

            # Membership in these two sets is what decides which fact(s) a row owes,
            # scoped to just this batch. Re-deriving that from a row's own fields
            # instead (e.g. "billing_sent_at is None") would also be true for a row
            # pulled in only because it owes the license fee while still RUNNING,
            # and would wrongly emit a completed event for a job that has not
            # finished.
            batch_pks = [row.pk for row in batch]
            license_fee_pks = set(
                JobOutbox.objects.pending_license_fee().filter(pk__in=batch_pks).values_list("pk", flat=True)
            )
            billing_event_pks = set(
                JobOutbox.objects.pending_billing_event().filter(pk__in=batch_pks).values_list("pk", flat=True)
            )

            for row in batch:
                if self.kill_signal.received:
                    return
                if time.monotonic() >= deadline:
                    logger.info("Time budget spent, stopping outbox drain for this tick")
                    return

                self._process_row(
                    row,
                    needs_license_fee=row.pk in license_fee_pks,
                    needs_billing_event=row.pk in billing_event_pks,
                )

    @staticmethod
    def _fetch_batch() -> list["JobOutbox"]:
        """Fetch one bounded batch of rows pending either fact, oldest first.

        BATCH_SIZE only bounds this single query's size; it is not the cap on how much a
        tick sends, that is run()'s time budget.
        """
        return list(
            (JobOutbox.objects.pending_license_fee() | JobOutbox.objects.pending_billing_event()).order_by(
                "status_changed_at"
            )[:BATCH_SIZE]
        )

    def _process_row(self, row: JobOutbox, *, needs_license_fee: bool, needs_billing_event: bool) -> None:
        """Send whichever facts this row owes, save once if anything changed, then delete if settled.

        The delete is a single DELETE ... WHERE statement carrying the
        ready_to_delete() predicate, not a separate exists() check followed by a
        conditional delete(): if the row is not actually ready, this just deletes
        zero rows, which is exactly as cheap as checking and skipping would have
        been, but never costs two round trips when it is ready.
        """
        changed = False

        if needs_license_fee:
            license_fee_sent_at = self._send_license_fee(row)
            if license_fee_sent_at is not None:
                row.license_fee_sent_at = license_fee_sent_at
                changed = True

        if needs_billing_event:
            billing_sent_at = self._send_billing_event(row)
            if billing_sent_at is not None:
                row.billing_sent_at = billing_sent_at
                changed = True

        if changed:
            row.save()

        JobOutbox.objects.ready_to_delete().filter(pk=row.pk).delete()

    def _send_license_fee(self, row: JobOutbox) -> datetime | None:
        """Attempt to send the license fee event. Returns the sent timestamp on success, None otherwise."""
        try:
            self.event_streams_client.emit_license_fee(row.job)
        except AttributeError as ex:
            logger.error(
                "job_id=%s license fee payload cannot be built, abandoning: %s",
                row.job_id,
                str(ex),
            )
            self.metrics.increment_outbox_license_fee_irrecoverable()
            return None
        except RuntimeError as ex:
            logger.error("job_id=%s error publishing license fee to Kafka: %s", row.job_id, str(ex))
            self.metrics.increment_outbox_send(FACT_LICENSE_FEE, "failure")
            self._breaker.record_failure()
            return None

        self.metrics.increment_outbox_send(FACT_LICENSE_FEE, "success")
        self._breaker.record_success()
        return timezone.now()

    def _send_billing_event(self, row: JobOutbox) -> datetime | None:
        """Attempt to send the final usage event. Returns the sent timestamp on success, None otherwise."""
        try:
            self.event_streams_client.emit_job_completed(row.job, row.status_changed_at)
        except RuntimeError as ex:
            logger.error("job_id=%s error publishing billing event to Kafka: %s", row.job_id, str(ex))
            self.metrics.increment_outbox_send(FACT_BILLING_EVENT, "failure")
            self._breaker.record_failure()
            return None

        self.metrics.increment_outbox_send(FACT_BILLING_EVENT, "success")
        self._breaker.record_success()
        return timezone.now()

    def _report_pending_gauges(self) -> None:
        """Report how many rows are pending each fact, and the oldest one's age."""
        now = timezone.now()
        for fact, queryset in (
            (FACT_LICENSE_FEE, JobOutbox.objects.pending_license_fee()),
            (FACT_BILLING_EVENT, JobOutbox.objects.pending_billing_event()),
        ):
            count = queryset.count()
            self.metrics.set_outbox_pending_rows(count, fact)
            oldest = queryset.order_by("status_changed_at").first()
            age_seconds = (now - oldest.status_changed_at).total_seconds() if oldest else 0
            self.metrics.set_outbox_oldest_pending_age_seconds(age_seconds, fact)
