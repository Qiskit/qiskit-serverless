"""Drain the outbox's two Kafka billing facts: the license fee and the final usage event.

See .claude/specs/2026-09-16-job-outbox-design.md, sections 9 and 9.1.
"""

import logging
import time

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

logger = logging.getLogger("scheduler.PublishKafkaOutbox")

FACT_LICENSE_FEE = "license_fee"
FACT_BILLING_EVENT = "billing_event"


class PublishKafkaOutbox(SchedulerTask):
    """Send the license fee and the final usage event for terminal Fleets jobs."""

    def __init__(self, kill_signal: KillSignal, metrics: SchedulerMetrics):
        self.kill_signal = kill_signal
        self.metrics = metrics
        self._event_streams_client: EventStreamsClient | None = None
        self._breaker = CircuitBreaker(
            failure_threshold=Config.get_int(ConfigKey.KAFKA_OUTBOX_BREAKER_FAILURES, default=5),
            pause_seconds=Config.get_int(ConfigKey.KAFKA_OUTBOX_BREAKER_PAUSE_SECONDS, default=60),
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
        """Drain one batch of pending outbox rows, within the configured time budget."""
        if not Config.get_bool(ConfigKey.KAFKA_OUTBOX_ENABLED):
            return

        self.metrics.set_outbox_kafka_breaker_open(self._breaker.is_open)
        self._report_pending_gauges()

        if self._breaker.is_open:
            return

        batch_size = Config.get_int(ConfigKey.KAFKA_OUTBOX_BATCH_SIZE, default=20)
        budget_ms = Config.get_int(ConfigKey.KAFKA_OUTBOX_BUDGET_MS, default=500)
        deadline = time.monotonic() + (budget_ms / 1000)

        rows = list(JobOutbox.objects.pending_kafka_outbox(limit=batch_size))
        for row in rows:
            if self.kill_signal.received:
                logger.info("Kill signal received, stopping Kafka outbox drain")
                return
            if time.monotonic() >= deadline:
                logger.info("Time budget spent, stopping Kafka outbox drain for this tick")
                return
            self._process_row(row)

    def _process_row(self, row: JobOutbox) -> None:
        """Send whatever this row still owes, then delete it if everything is settled.

        row.save() is only called when a send actually changed a field: a row that
        failed every attempt it made this pass must be left untouched, so the next
        pass still finds it via pending_kafka_outbox instead of relying on a write
        that recorded nothing.
        """
        changed = False

        if row.license_fee_required and row.license_fee_sent_at is None:
            changed |= self._send_license_fee(row)

        if row.billing_sent_at is None:
            changed |= self._send_billing_event(row)

        if changed:
            row.save()

        if JobOutbox.objects.ready_to_delete().filter(pk=row.pk).exists():
            row.delete()

    def _send_license_fee(self, row: JobOutbox) -> bool:
        """Attempt to send the license fee event. Returns True if the row changed."""
        try:
            self.event_streams_client.emit_license_fee(row.job)
        except AttributeError as ex:
            logger.error(
                "job_id=%s license fee payload cannot be built, abandoning: %s",
                row.job_id,
                str(ex),
            )
            self.metrics.increment_outbox_license_fee_irrecoverable()
            return False
        except RuntimeError as ex:
            logger.error("job_id=%s error publishing license fee to Kafka: %s", row.job_id, str(ex))
            self.metrics.increment_outbox_kafka_send(FACT_LICENSE_FEE, "failure")
            self._breaker.record_failure()
            return False

        row.license_fee_sent_at = timezone.now()
        self.metrics.increment_outbox_kafka_send(FACT_LICENSE_FEE, "success")
        self._breaker.record_success()
        return True

    def _send_billing_event(self, row: JobOutbox) -> bool:
        """Attempt to send the final usage event. Returns True if the row changed."""
        try:
            self.event_streams_client.emit_job_completed(row.job, row.status_changed_at)
        except RuntimeError as ex:
            logger.error("job_id=%s error publishing billing event to Kafka: %s", row.job_id, str(ex))
            self.metrics.increment_outbox_kafka_send(FACT_BILLING_EVENT, "failure")
            self._breaker.record_failure()
            return False

        row.billing_sent_at = timezone.now()
        self.metrics.increment_outbox_kafka_send(FACT_BILLING_EVENT, "success")
        self._breaker.record_success()
        return True

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
