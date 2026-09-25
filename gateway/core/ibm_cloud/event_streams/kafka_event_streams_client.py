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

"""Kafka-backed Event Streams client for the two best-effort, inline-published events:
job_started and job_in_progress. The other two facts that used to live here (license fee, job
completed) are now built by core/domain/billing_events.py and sent by KafkaOutboxSender, never
inline: see .claude/specs/2026-09-25-generic-outbox-design.md (local, not committed).
"""

from __future__ import annotations

import json
import logging
import math
import uuid
from datetime import datetime, timezone

from core.models import Job, JobEvent

from .abstract_event_streams_client import EventStreamsClient
from .kafka_producers import KafkaProducers

logger = logging.getLogger("gateway.ibm_cloud.event_streams_client")

CLASSICAL_TIME_METRIC_TYPE_PREFIX = "classical"


class KafkaEventStreamsClient(EventStreamsClient):
    """Publishes CloudEvents 1.0 usage events for the two events sent inline, best-effort:
    job_started and job_in_progress. See KafkaProducers for how producers/topic are configured.
    """

    def __init__(self, producers: KafkaProducers | None = None) -> None:
        self._producers = producers or KafkaProducers()

    @property
    def topic(self) -> str:
        return self._producers.topic

    def _emit_job_started(self, job: Job, metric_type: str | None = None) -> None:
        """Publish a job-started event for the given metric (metric_value=0)."""
        if metric_type is None:
            metric_type = self._build_classical_metric_type(job)
        logger.info("job_id=%s Emitting job_started event metric_type=%s", job.id, metric_type)
        running_started_at = JobEvent.objects.first_running_at(job.id)
        self._publish(
            job,
            metric_type=metric_type,
            metric_value=0,
            job_started=True,
            job_completed=False,
            running_started_at=running_started_at,
        )

    def _emit_job_in_progress(self, job: Job, metric_type: str | None = None) -> None:
        """Publish a job-in-progress event for the given metric with current usage."""
        if metric_type is None:
            metric_type = self._build_classical_metric_type(job)
        running_started_at = JobEvent.objects.first_running_at(job.id)
        usage_seconds = self._usage_seconds(running_started_at, datetime.now(timezone.utc))
        logger.info(
            "job_id=%s Emitting job_in_progress event metric_type=%s metric_value=%s",
            job.id,
            metric_type,
            usage_seconds,
        )
        self._publish(
            job,
            metric_type=metric_type,
            metric_value=usage_seconds,
            job_started=False,
            job_completed=False,
            running_started_at=running_started_at,
        )

    def _build_classical_metric_type(self, job: Job) -> str:
        """Build classical metric type from job attributes: classical_COMPUTE_PROFILE."""
        parts = [CLASSICAL_TIME_METRIC_TYPE_PREFIX]
        if job.compute_profile:
            parts.append(job.compute_profile)
        return "_".join(parts)

    def _usage_seconds(self, running_started_at: datetime | None, as_of: datetime) -> int:
        """Usage in whole seconds up to as_of, rounded up so any partial second is billed."""
        if running_started_at is None:
            return 0
        delta = as_of - running_started_at
        return math.ceil(delta.total_seconds())

    def _delivery_callback(self, err, msg):
        """Callback for message delivery reports."""
        if err is not None:
            logger.error(
                "Message delivery failed topic=%s partition=%s error=%s error_code=%s",
                msg.topic() if msg else "unknown",
                msg.partition() if msg else "unknown",
                err,
                err.code() if hasattr(err, "code") else "unknown",
            )

    def _publish(
        self,
        job: Job,
        *,
        metric_type: str,
        metric_value: int,
        job_started: bool,
        job_completed: bool,
        running_started_at: datetime | None,
    ) -> None:
        now = datetime.now(timezone.utc)
        event_id = str(uuid.uuid4())

        event = {
            "specversion": "1.0",
            "id": event_id,
            "source": "qiskit-serverless/scheduler/fleets",
            "type": self.topic,
            "time": now.isoformat(),
            "subject": str(job.id),
            "datacontenttype": "application/json",
            "data": {
                "metric_type": metric_type,
                "metric_value": metric_value,
                "instance_crn": job.instance_crn,
                "resource_id": str(job.id),
                "job_started": job_started,
                "job_started_at": running_started_at.isoformat() if running_started_at else None,
                "job_completed": job_completed,
            },
        }

        producer = self._producers.get(job.instance_crn)  # raises UnroutableRegionError

        try:
            producer.produce(
                topic=self.topic,
                key=str(job.id).encode("utf-8"),
                value=json.dumps(event).encode("utf-8"),
                callback=self._delivery_callback,
            )
            remaining = producer.flush(timeout=5)
            if remaining > 0:
                raise RuntimeError(f"KafkaEventStreamsClient: {remaining} message(s) not delivered after flush timeout")
        except Exception as e:
            raise RuntimeError(
                f"KafkaEventStreamsClient: Failed to publish event "
                f"(job_id={job.id}, event_id={event_id}, metric_type={metric_type}): {str(e)}"
            ) from e
