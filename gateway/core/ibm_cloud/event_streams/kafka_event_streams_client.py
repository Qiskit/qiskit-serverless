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
import math
import os
import uuid
from datetime import datetime, timezone

from confluent_kafka import Producer
from core.domain.business_models import billing_name_for
from core.models import Job, JobEvent

from .abstract_event_streams_client import EventStreamsClient

logger = logging.getLogger("gateway.ibm_cloud.event_streams_client")

LICENSE_FEE_METRIC_TYPE = "license"
CLASSICAL_TIME_METRIC_TYPE_PREFIX = "classical"


class UnroutableRegionError(RuntimeError):
    """Raised when an event cannot be routed to a producer: the CRN's region could not be
    determined, or no producer is configured for that region.

    Unlike a plain RuntimeError from a failed produce()/flush() call, this is not a
    transient Kafka outage: it is either bad data on the row or a deployment config gap,
    and neither is fixed by pausing sends, so callers should not count it against a shared
    circuit breaker.
    """


class KafkaEventStreamsClient(EventStreamsClient):
    """
    Kafka producer client for IBM Cloud Event Streams.

    Publishes CloudEvents 1.0 usage events for Fleets jobs. Each event carries a
    single metric in its `data` payload: `metric_type` (what is being billed) and
    `metric_value` (how much, in whole seconds for time-based metrics), plus
    `job_started` / `job_completed` flags so consumers can detect lifecycle
    boundaries without interpreting the metric type. License fee events also
    carry `business_model`.

    Configured from environment variables per region:
      EVENT_STREAMS_BOOTSTRAP_SERVERS         — comma-separated broker list (main region)
      EVENT_STREAMS_API_KEY                   — SASL/PLAIN password (main region)
      EVENT_STREAMS_USER                      — SASL/PLAIN username (default: 'token')
      EVENT_STREAMS_BOOTSTRAP_SERVERS_<REGION> — broker list for additional regions
      EVENT_STREAMS_API_KEY_<REGION>          — API key for additional regions
      EVENT_STREAMS_USER_<REGION>             — SASL/PLAIN username for additional regions
      EVENT_STREAMS_MAIN_REGION               — main region (default: us-east)
      ENVIRONMENT                             — deployment environment (e.g. production, staging)
    """

    def __init__(self) -> None:
        environment = os.environ["ENVIRONMENT"]

        # Initialize producers from environment variables
        self._producers: dict[str, Producer] = {}

        # Register main region from unsuffixed variables
        main_bootstrap_servers = os.environ.get("EVENT_STREAMS_BOOTSTRAP_SERVERS")
        main_api_key = os.environ.get("EVENT_STREAMS_API_KEY")
        main_user = os.environ.get("EVENT_STREAMS_USER", "token")
        main_region = os.environ.get("EVENT_STREAMS_MAIN_REGION", "us-east")

        if main_bootstrap_servers and main_api_key:
            logger.info("Registering main region producer: region=%s", main_region)
            self._producers[main_region] = self._create_producer(main_bootstrap_servers, main_api_key, main_user)
            self._main_region = main_region
        else:
            raise ValueError("EVENT_STREAMS_BOOTSTRAP_SERVERS and EVENT_STREAMS_API_KEY are required")

        # Discover regional producers by scanning for suffixed env vars
        for env_key in os.environ:
            if env_key.startswith("EVENT_STREAMS_BOOTSTRAP_SERVERS_"):
                suffix = env_key[len("EVENT_STREAMS_BOOTSTRAP_SERVERS_") :]
                region = suffix.lower().replace("_", "-")
                logger.info("Discovered environment variable for region: env_key=%s region=%s", env_key, region)
                bootstrap_servers = os.environ[env_key]
                api_key_env = f"EVENT_STREAMS_API_KEY_{suffix}"
                user_env = f"EVENT_STREAMS_USER_{suffix}"
                api_key = os.environ.get(api_key_env)
                user = os.environ.get(user_env, "token")

                if api_key is None:
                    raise ValueError(f"Region {region}: found {env_key} but missing {api_key_env}")

                logger.info("Registering regional producer: region=%s", region)
                self._producers[region] = self._create_producer(bootstrap_servers, api_key, user)

        self.topic = f"quantum.{environment}.function-usage.v1"

        # Log initialized regions
        regions = sorted(self._producers.keys())
        logger.info(
            "Event Streams producers initialized: regions=%s (main=%s)",
            regions,
            main_region,
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

    def _emit_job_started(self, job: Job, metric_type: str | None = None) -> None:
        """Publish a job-started event for the given metric (metric_value=0)."""
        if metric_type is None:
            metric_type = self._build_classical_metric_type(job)
        logger.info("job_id=%s Emitting job_started event", job.id)
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
        self._publish(
            job,
            metric_type=metric_type,
            metric_value=usage_seconds,
            job_started=False,
            job_completed=False,
            running_started_at=running_started_at,
        )

    def _emit_job_completed(self, job: Job, ended_at: datetime, metric_type: str | None = None) -> None:
        """Publish a job-completed event for the given metric with final usage as of ended_at."""
        if metric_type is None:
            metric_type = self._build_classical_metric_type(job)
        running_started_at = JobEvent.objects.first_running_at(job.id)
        usage_seconds = self._usage_seconds(running_started_at, ended_at)
        logger.info("job_id=%s Emitting job_completed event metric_value=%s", job.id, usage_seconds)
        self._publish(
            job,
            metric_type=metric_type,
            metric_value=usage_seconds,
            job_started=False,
            job_completed=True,
            running_started_at=running_started_at,
        )

    def _emit_license_fee(self, job: Job) -> None:
        """Publish a license fee event.

        Assumes job.program and job.program.provider are present: both are SET_NULL
        foreign keys that can go null, so the caller (PublishOutbox) checks for that
        before calling this and waives the fee instead of calling it. A stray
        AttributeError here is a real bug and is not caught by the caller.
        """
        parts = [LICENSE_FEE_METRIC_TYPE, job.program.provider.name, job.program.title]

        # Include function size; all Fleets jobs have one (see PR #2490)
        function_size = self._resolve_function_size(job)
        parts.append(function_size)

        metric_type = "_".join(parts)
        running_started_at = JobEvent.objects.first_running_at(job.id)
        self._publish(
            job,
            metric_type=metric_type,
            metric_value=1,
            job_started=True,
            job_completed=True,
            business_model=billing_name_for(job.business_model),
            running_started_at=running_started_at,
        )

    def _resolve_function_size(self, job: Job) -> str:
        """Resolve the function size for the job.

        All Fleets jobs have an explicit size set (see PR #2490).
        """
        return job.function_size.function_size

    def _resolve_function_size(self, job: Job) -> str:
        """Resolve the function size for the job.

        All Fleets jobs have an explicit size set (see PR #2490).
        """
        return job.function_size.function_size

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
            "job_started_at": running_started_at.isoformat() if running_started_at else None,
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
            raise UnroutableRegionError(
                f"KafkaEventStreamsClient: Cannot determine region from CRN "
                f"(job_id={job.id}, event_id={event_id}, crn={job.instance_crn})"
            )
        producer = self._producers.get(region)
        if producer is None:
            raise UnroutableRegionError(
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
