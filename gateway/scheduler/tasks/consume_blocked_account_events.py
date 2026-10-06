"""Consume blocked-account-plan events from Kafka."""

import logging

from django.conf import settings

from core.ibm_cloud.event_streams.kafka_consumer import KafkaBlockedAccountsConsumer

from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from .task import SchedulerTask

logger = logging.getLogger("scheduler.ConsumeBlockedAccountEvents")


class ConsumeBlockedAccountEvents(SchedulerTask):
    """Drain the blocked-account-plan events the regions have queued, within this tick."""

    def __init__(self, kill_signal: KillSignal, metrics: SchedulerMetrics):
        self.kill_signal = kill_signal
        self.metrics = metrics
        # One consumer per region, created once and reused by every tick.
        self.consumer = KafkaBlockedAccountsConsumer() if settings.EVENT_STREAMS_ENABLED else None
        if self.consumer is None:
            logger.info("EVENT_STREAMS_ENABLED is False, blocked-account events will not be consumed")

    def run(self) -> None:
        """Handle whatever every region has queued, and return."""
        if self.consumer is None:
            return
        self.consumer.drain(lambda: self.kill_signal.received)
