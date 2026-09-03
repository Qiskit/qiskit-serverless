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
from core.domain.business_models import billing_name_for
from core.models import Job

from .abstract_event_streams_client import EventStreamsClient

logger = logging.getLogger("gateway.ibm_cloud.event_streams_client")

LICENSE_FEE_METRIC_TYPE = "license"
CLASSICAL_TIME_METRIC_TYPE_PREFIX = "classical"


class KafkaEventStreamsClient(EventStreamsClient):
    """
    Kafka producer client for IBM Cloud Event Streams.

    Publishes CloudEvents 1.0 usage events for Fleets jobs. Each event carries a
    single metric in its `data` payload: `metric_type` (what is being billed) and
    `metric_value` (how much, in milliseconds for time-based metrics), plus
    `job_started` / `job_completed` flags so consumers can detect lifecycle
    boundaries without interpreting the metric type. License fee events also
    carry `business_model`.

    Configured from environment variables per region:
      EVENT_STREAMS_BOOTSTRAP_SERVERS         — comma-separated broker list (default region)
      EVENT_STREAMS_API_KEY                   — SASL/PLAIN password (default region)
      EVENT_STREAMS_USER                      — SASL/PLAIN username (default: 'token')
      EVENT_STREAMS_BOOTSTRAP_SERVERS_<REGION> — broker list for additional regions
      EVENT_STREAMS_API_KEY_<REGION>          — API key for additional regions
      EVENT_STREAMS_USER_<REGION>             — SASL/PLAIN username for additional regions
      EVENT_STREAMS_DEFAULT_REGION            — default region (default: us-east)
      ENVIRONMENT                             — deployment environment (e.g. production, staging)
    """

    def __init__(self) -> None:
        environment = os.environ["ENVIRONMENT"]
        default_region = os.environ.get("EVENT_STREAMS_DEFAULT_REGION", "us-east")

        # Initialize producers from environment variables
        self._producers: dict[str, Producer] = {}
        self._default_region = default_region

        # Register default region from unsuffixed variables
        default_bootstrap_servers = os.environ.get("EVENT_STREAMS_BOOTSTRAP_SERVERS")
        default_api_key = os.environ.get("EVENT_STREAMS_API_KEY")
        default_user = os.environ.get("EVENT_STREAMS_USER", "token")
        if default_bootstrap_servers and default_api_key:
            logger.debug("Registering default region producer: region=%s", default_region)
            self._producers[default_region] = self._create_producer(
                default_bootstrap_servers, default_api_key, default_user
            )

        # Discover regional producers by scanning for suffixed env vars
        for env_key in os.environ:
            if env_key.startswith("EVENT_STREAMS_BOOTSTRAP_SERVERS_"):
                suffix = env_key[len("EVENT_STREAMS_BOOTSTRAP_SERVERS_") :]
                region = suffix.lower().replace("_", "-")
                bootstrap_servers = os.environ[env_key]
                api_key_env = f"EVENT_STREAMS_API_KEY_{suffix}"
                user_env = f"EVENT_STREAMS_USER_{suffix}"
                api_key = os.environ.get(api_key_env)
                user = os.environ.get(user_env, "token")

                if api_key is None:
                    raise ValueError(f"Region {region}: found {env_key} but missing {api_key_env}")

                logger.debug("Registering regional producer: region=%s", region)
                self._producers[region] = self._create_producer(bootstrap_servers, api_key, user)

        self.topic = f"quantum.{environment}.function-usage.v1"

        # Log initialized regions
        regions = sorted(self._producers.keys())
        logger.info(
            "Event Streams producers initialized: regions=%s (default=%s)",
            regions,
            default_region,
        )

    def _create_producer(self, bootstrap_servers: str, api_key: str, user: str = "token") -> Producer:
        """Create and return a Kafka producer with the given credentials."""
        return Producer(
            {
                "bootstrap.servers": bootstrap_servers,
                "security.protocol": "SASL_SSL",
                "sasl.mechanisms": "PLAIN",
                "sasl.username": user,
                "sasl.password": api_key,
                "enable.idempotence": True,
                "acks": "all",
            }
        )

    @staticmethod
    def _region_from_crn(instance_crn: str | None) -> str | None:
        """Extract the region from an instance CRN.

        The region is the 6th colon-delimited segment of the CRN
        (crn:v1:bluemix:public:quantum-computing:<region>:...).
        Returns None if the CRN is absent or has too few segments.
        """
        if not instance_crn:
            return None
        parts = instance_crn.split(":")
        if len(parts) > 5:
            return parts[5]
        return None

    def _emit_job_started(self, job, metric_type: str | None = None) -> None:
        """Publish a job-started event for the given metric (metric_value=0)."""
        if metric_type is None:
            metric_type = self._build_classical_metric_type(job)
        logger.info("job_id=%s Emitting job_started event", job.id)
        self._publish(job, metric_type=metric_type, metric_value=0, job_started=True, job_completed=False)

    def _emit_job_in_progress(self, job, metric_type: str | None = None) -> None:
        """Publish a job-in-progress event for the given metric with current usage."""
        if metric_type is None:
            metric_type = self._build_classical_metric_type(job)
        self._publish(
            job,
            metric_type=metric_type,
            metric_value=self._usage_ms(job),
            job_started=False,
            job_completed=False,
        )

    def _emit_job_completed(self, job, metric_type: str | None = None) -> None:
        """Publish a job-completed event for the given metric with final usage."""
        if metric_type is None:
            metric_type = self._build_classical_metric_type(job)
        usage_ms = self._usage_ms(job)
        logger.info("job_id=%s Emitting job_completed event metric_value=%s", job.id, usage_ms)
        self._publish(
            job,
            metric_type=metric_type,
            metric_value=usage_ms,
            job_started=False,
            job_completed=True,
        )

    def _emit_license_fee(self, job: Job) -> None:
        metric_type = "_".join([LICENSE_FEE_METRIC_TYPE, job.program.provider.name, job.program.title])
        self._publish(
            job,
            metric_type=metric_type,
            metric_value=1,
            job_started=True,
            job_completed=True,
            business_model=billing_name_for(job.business_model),
        )

    def _build_classical_metric_type(self, job: Job) -> str:
        """Build classical metric type from job attributes: classical_COMPUTE_PROFILE."""
        parts = [CLASSICAL_TIME_METRIC_TYPE_PREFIX]

        if job.compute_profile:
            parts.append(job.compute_profile)

        return "_".join(parts)

    def _usage_ms(self, job) -> int:
        if job.running_started_at is None:
            return 0
        delta = datetime.now(timezone.utc) - job.running_started_at
        return int(delta.total_seconds() * 1e3)

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
        business_model: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        event_id = str(uuid.uuid4())

        data = {
            "metric_type": metric_type,
            "metric_value": metric_value,
            "instance_crn": job.instance_crn,
            "resource_id": str(job.id),
            "job_started": job_started,
            "job_started_at": job.running_started_at.isoformat() if job.running_started_at else None,
            "job_completed": job_completed,
        }
        if business_model is not None:
            data["business_model"] = business_model

        event = {
            "specversion": "1.0",
            "id": event_id,
            "source": "qiskit-serverless/scheduler/fleets",
            "type": self.topic,
            "time": now.isoformat(),
            "subject": str(job.id),
            "datacontenttype": "application/json",
            "data": data,
        }

        # Route to the appropriate regional producer
        region = self._region_from_crn(job.instance_crn)
        if region is None:
            region = self._default_region
        producer = self._producers.get(region)
        if producer is None:
            raise RuntimeError(
                f"KafkaEventStreamsClient: No producer configured for region {region} "
                f"(job_id={job.id}, event_id={event_id})"
            )

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
