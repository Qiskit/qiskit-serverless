"""Consume blocked-account-plan events from Kafka."""

import logging

from django.conf import settings

from core.ibm_cloud.event_streams import kafka_consumer
from core.ibm_cloud.event_streams.kafka_consumer import DrainStats, KafkaRegionalConsumer
from core.services.blocked_account_events import handle_blocked_account_event

from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from .task import SchedulerTask

logger = logging.getLogger("scheduler.ConsumeBlockedAccountEvents")

# DrainStats outcome -> label of scheduler_blocked_account_events_total
_EVENT_OUTCOMES = {
    kafka_consumer.HANDLED: "handled",
    kafka_consumer.INVALID: "invalid",
    kafka_consumer.TOMBSTONE: "tombstone",
    kafka_consumer.RETRY: "retry",
}
# DrainStats outcome -> label of scheduler_blocked_account_consumer_errors_total
_ERROR_KINDS = {
    kafka_consumer.CONSUMER_ERROR: "consumer",
    kafka_consumer.COMMIT_ERROR: "commit",
    kafka_consumer.FATAL: "fatal",
}


def blocked_accounts_topics(environment: str) -> list[str]:
    """The topics the blocked-account-plan events are published to."""
    return [
        f"quantum.{environment}.blocked-account-plans.v1",
        f"quantum.{environment}.blocked-account-plans-non-quantum.v1",
    ]


class ConsumeBlockedAccountEvents(SchedulerTask):
    """Drain the blocked-account-plan events the regions have queued, within this tick."""

    def __init__(self, kill_signal: KillSignal, metrics: SchedulerMetrics):
        self.kill_signal = kill_signal
        self.metrics = metrics
        # One consumer per region, created once and reused by every tick.
        self.consumer: KafkaRegionalConsumer | None = None
        if settings.EVENT_STREAMS_ENABLED:
            self.consumer = KafkaRegionalConsumer(
                topics=blocked_accounts_topics(settings.ENVIRONMENT),
                group_id=f"qiskit-serverless-scheduler-blocked-accounts-{settings.ENVIRONMENT}",
                handler=handle_blocked_account_event,
            )
        else:
            logger.info("EVENT_STREAMS_ENABLED is False, blocked-account events will not be consumed")

    def run(self) -> None:
        """Handle whatever every region has queued, and return. Raises the first event whose
        handling failed transiently, once the others are done, for the loop to record it."""
        if self.consumer is None:
            return
        stats = DrainStats()
        try:
            self.consumer.drain(lambda: self.kill_signal.received, stats)
        finally:
            self._report(stats)

    def close(self) -> None:
        """Have every region's consumer leave its group now, so its partitions are reassigned at once."""
        if self.consumer is not None:
            self.consumer.close()

    def _report(self, stats: DrainStats) -> None:
        """Turn what the drain counted into metrics."""
        for (region, outcome), count in stats.counts.items():
            if outcome in _EVENT_OUTCOMES:
                self.metrics.increment_blocked_account_event(region, _EVENT_OUTCOMES[outcome], count)
            elif outcome in _ERROR_KINDS:
                self.metrics.increment_blocked_account_consumer_error(region, _ERROR_KINDS[outcome], count)
