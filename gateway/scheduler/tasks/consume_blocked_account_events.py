# This code is part of a Qiskit project.
#
# (C) IBM 2026
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Consume blocked-account-plan events from Kafka."""

import logging

from django.conf import settings

from core.ibm_cloud.event_streams.abstract_event_streams_client import EventStreamsClient
from core.ibm_cloud.event_streams.kafka_event_streams_client import KafkaEventStreamsClient
from core.ibm_cloud.event_streams.noop_event_streams_client import NoOpEventStreamsClient

from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from .task import SchedulerTask

logger = logging.getLogger("scheduler.ConsumeBlockedAccountEvents")


class ConsumeBlockedAccountEvents(SchedulerTask):
    """Consume and process blocked-account-plan events from Kafka."""

    def __init__(self, kill_signal: KillSignal, metrics: SchedulerMetrics):
        self.kill_signal = kill_signal
        self.metrics = metrics
        self._event_streams_client: EventStreamsClient | None = None

    @property
    def event_streams_client(self) -> EventStreamsClient:
        """Return the Event Streams client, instantiating it lazily on first access."""
        if self._event_streams_client is None:
            if settings.EVENT_STREAMS_ENABLED:
                logger.info(
                    "Initializing KafkaEventStreamsClient for blocked-account consumption (EVENT_STREAMS_ENABLED=True)"
                )
                self._event_streams_client = KafkaEventStreamsClient()
            else:
                logger.info(
                    "Initializing NoOpEventStreamsClient for blocked-account consumption (EVENT_STREAMS_ENABLED=False)"
                )
                self._event_streams_client = NoOpEventStreamsClient()
        return self._event_streams_client

    def run(self) -> None:
        """Consume pending blocked-account events."""
        self.event_streams_client.consume_events()
