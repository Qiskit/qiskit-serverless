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

"""No-op Event Streams client for use when publishing is disabled."""

import logging

from .abstract_event_streams_client import EventStreamsClient

logger = logging.getLogger("gateway.ibm_cloud.event_streams_client")


class NoOpEventStreamsClient(EventStreamsClient):
    """
    Drop-in replacement for KafkaEventStreamsClient when EVENT_STREAMS_ENABLED is false.

    Logs each emit call at DEBUG level instead of publishing to Kafka.
    """

    def emit_job_started(self, job) -> None:
        logger.info("job_id=%s [noop] emit_job_started", job.id)

    def emit_job_in_progress(self, job) -> None:
        logger.info("job_id=%s [noop] emit_job_in_progress", job.id)

    def emit_job_ended(self, job) -> None:
        logger.info("job_id=%s [noop] emit_job_ended", job.id)
