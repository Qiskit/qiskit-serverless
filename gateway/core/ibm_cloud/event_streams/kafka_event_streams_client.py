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
import time
import uuid
from datetime import datetime, timezone

from confluent_kafka import Consumer, Producer
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
        # Store region configs for consumer creation (credentials needed for both)
        self._region_configs: dict[str, dict] = {}

        # Register main region from unsuffixed variables
        main_bootstrap_servers = os.environ.get("EVENT_STREAMS_BOOTSTRAP_SERVERS")
        main_api_key = os.environ.get("EVENT_STREAMS_API_KEY")
        main_user = os.environ.get("EVENT_STREAMS_USER", "token")
        main_region = os.environ.get("EVENT_STREAMS_MAIN_REGION", "us-east")

        if main_bootstrap_servers and main_api_key:
            logger.debug("Registering main region producer: region=%s", main_region)
            self._producers[main_region] = self._create_producer(main_bootstrap_servers, main_api_key, main_user)
            self._region_configs[main_region] = {
                "bootstrap_servers": main_bootstrap_servers,
                "api_key": main_api_key,
                "user": main_user,
            }
            self._main_region = main_region
        else:
            raise ValueError("EVENT_STREAMS_BOOTSTRAP_SERVERS and EVENT_STREAMS_API_KEY are required")

        # Discover regional producers by scanning for suffixed env vars
        for env_key in os.environ:
            if env_key.startswith("EVENT_STREAMS_BOOTSTRAP_SERVERS_"):
                suffix = env_key[len("EVENT_STREAMS_BOOTSTRAP_SERVERS_") :]
                region = suffix.lower().replace("_", "-")
                logger.debug("Discovered environment variable for region: env_key=%s region=%s", env_key, region)
                bootstrap_servers = os.environ[env_key]
                api_key_env = f"EVENT_STREAMS_API_KEY_{suffix}"
                user_env = f"EVENT_STREAMS_USER_{suffix}"
                api_key = os.environ.get(api_key_env)
                user = os.environ.get(user_env, "token")

                if api_key is None:
                    raise ValueError(f"Region {region}: found {env_key} but missing {api_key_env}")

                logger.debug("Registering regional producer: region=%s", region)
                self._producers[region] = self._create_producer(bootstrap_servers, api_key, user)
                self._region_configs[region] = {
                    "bootstrap_servers": bootstrap_servers,
                    "api_key": api_key,
                    "user": user,
                }

        self.topic = f"quantum.{environment}.function-usage.v1"
        self.blocked_accounts_topic = os.environ.get(
            "EVENT_STREAMS_BLOCKED_ACCOUNTS_TOPIC", "blocked-account-plans-non-quantum.v1"
        )
        self._blocked_accounts_group_id = f"qiskit-serverless-scheduler-blocked-accounts-{environment}"
        self._consumers: dict[str, Consumer] = {}

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
            metric_value=self._usage_seconds(job),
            job_started=False,
            job_completed=False,
        )

    def _emit_job_completed(self, job, metric_type: str | None = None) -> None:
        """Publish a job-completed event for the given metric with final usage."""
        if metric_type is None:
            metric_type = self._build_classical_metric_type(job)
        usage_seconds = self._usage_seconds(job)
        logger.info("job_id=%s Emitting job_completed event metric_value=%s", job.id, usage_seconds)
        self._publish(
            job,
            metric_type=metric_type,
            metric_value=usage_seconds,
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

    def _usage_seconds(self, job) -> int:
        """Usage in whole seconds, rounded up so that any partial second is billed."""
        if job.running_started_at is None:
            return 0
        delta = datetime.now(timezone.utc) - job.running_started_at
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
            raise RuntimeError(
                f"KafkaEventStreamsClient: Cannot determine region from CRN "
                f"(job_id={job.id}, event_id={event_id}, crn={job.instance_crn})"
            )
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

    def _get_consumer(self, region: str) -> Consumer:
        """Get or create a consumer for the given region."""
        if region in self._consumers:
            return self._consumers[region]

        config = self._region_configs[region]
        consumer = Consumer(
            {
                "bootstrap.servers": config["bootstrap_servers"],
                "security.protocol": "SASL_SSL",
                "sasl.mechanisms": "PLAIN",
                "sasl.username": config["user"],
                "sasl.password": config["api_key"],
                "group.id": self._blocked_accounts_group_id,
                "enable.auto.commit": False,
                "auto.offset.reset": "earliest",
            }
        )
        consumer.subscribe([self.blocked_accounts_topic])
        self._consumers[region] = consumer
        logger.debug("Created consumer for region: region=%s topic=%s", region, self.blocked_accounts_topic)
        return consumer

    def _deserialize_blocked_account_event(self, msg) -> dict:
        """Deserialize a blocked-account-plan event (JSON payload)."""
        return json.loads(msg.value().decode("utf-8"))

    def _poll_region(self, region: str, consumer: Consumer) -> None:
        """Poll and process blocked-account events from one region (bounded per iteration)."""
        max_messages = 500
        deadline = time.time() + 2.0
        messages_processed = 0

        while time.time() < deadline and messages_processed < max_messages:
            msg = consumer.poll(timeout=0.2)
            if msg is None:
                break

            if msg.error():
                logger.error(
                    "Consumer error for region=%s error=%s",
                    region,
                    msg.error(),
                )
                continue

            try:
                event = self._deserialize_blocked_account_event(msg)
                logger.info(
                    "Blocked account event: region=%s account_id=%s plan_id=%s "
                    "subscription_id=%s deleted=%s total_non_quantum_micro_ru=%s "
                    "non_quantum_limit_micro_ru=%s",
                    region,
                    event.get("account_id"),
                    event.get("plan_id"),
                    event.get("subscription_id"),
                    event.get("deleted"),
                    event.get("total_non_quantum_micro_ru"),
                    event.get("non_quantum_limit_micro_ru"),
                )
                messages_processed += 1
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error(
                    "Failed to process blocked account event: region=%s error=%s",
                    region,
                    str(e),
                )

        if messages_processed > 0:
            try:
                consumer.commit(asynchronous=False)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error(
                    "Failed to commit offsets for region=%s error=%s",
                    region,
                    str(e),
                )

    def consume_events(self) -> None:
        """Poll pending blocked-account-plan events and process them."""
        for region in self._producers:
            try:
                consumer = self._get_consumer(region)
                self._poll_region(region, consumer)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error(
                    "Error consuming blocked-account events from region=%s error=%s",
                    region,
                    str(e),
                )
