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

"""Kafka-backed Event Streams client for IBM Cloud Event Streams."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone

from confluent_kafka import Producer

from .abstract_event_streams_client import EventStreamsClient

logger = logging.getLogger("gateway.ibm_cloud.event_streams_client")

LICENSE_FEE_METRIC_TYPE = "license"


class KafkaEventStreamsClient(EventStreamsClient):
    """
    Kafka producer client for IBM Cloud Event Streams.

    Publishes CloudEvents 1.0 usage events for Fleets jobs. Each event carries a
    single metric in its `data` payload: `metric_type` (what is being billed) and
    `metric_value` (how much, in milliseconds for time-based metrics), plus
    `job_started` / `job_completed` flags so consumers can detect lifecycle
    boundaries without interpreting the metric type.

    Configured from environment variables:
      EVENT_STREAMS_BOOTSTRAP_SERVERS — comma-separated broker list
      EVENT_STREAMS_API_KEY           — SASL/PLAIN password
      ENVIRONMENT                     — deployment environment (e.g. production, staging)
    """

    def __init__(self) -> None:
        bootstrap_servers = os.environ["EVENT_STREAMS_BOOTSTRAP_SERVERS"]
        api_key = os.environ["EVENT_STREAMS_API_KEY"]
        environment = os.environ["ENVIRONMENT"]

        self._producer = Producer(
            {
                "bootstrap.servers": bootstrap_servers,
                "security.protocol": "SASL_SSL",
                "sasl.mechanisms": "PLAIN",
                "sasl.username": "token",
                "sasl.password": api_key,
            }
        )
        self.topic = f"quantum.{environment}.function-usage.v1"

    def emit_job_started(self, job, metric_type: str) -> None:
        """Publish a job-started event for the given metric (metric_value=0)."""
        self._publish(job, metric_type=metric_type, metric_value=0, job_started=True, job_completed=False)

    def emit_job_in_progress(self, job, metric_type: str) -> None:
        """Publish a job-in-progress event for the given metric with current usage."""
        self._publish(
            job,
            metric_type=metric_type,
            metric_value=self._usage_ms(job),
            job_started=False,
            job_completed=False,
        )

    def emit_job_completed(self, job, metric_type: str) -> None:
        """Publish a job-completed event for the given metric with final usage."""
        self._publish(
            job,
            metric_type=metric_type,
            metric_value=self._usage_ms(job),
            job_started=False,
            job_completed=True,
        )

    def emit_license_fee(self, job) -> None:
        self._publish(
            job,
            metric_type=LICENSE_FEE_METRIC_TYPE,
            metric_value=1,
            job_started=True,
            job_completed=False,
        )

    def _usage_ms(self, job) -> int:
        if job.running_started_at is None:
            return 0
        delta = datetime.now(timezone.utc) - job.running_started_at
        return int(delta.total_seconds() * 1e3)

    def _publish(
        self,
        job,
        *,
        metric_type: str,
        metric_value: int,
        job_started: bool,
        job_completed: bool,
    ) -> None:
        now = datetime.now(timezone.utc)
        event = {
            "specversion": "1.0",
            "id": str(uuid.uuid4()),
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
                "job_completed": job_completed,
            },
        }
        self._producer.produce(
            topic=self.topic,
            key=str(job.id).encode("utf-8"),
            value=json.dumps(event).encode("utf-8"),
        )
        remaining = self._producer.flush(timeout=5)
        if remaining > 0:
            raise RuntimeError(f"KafkaEventStreamsClient: {remaining} message(s) not delivered after flush timeout")
