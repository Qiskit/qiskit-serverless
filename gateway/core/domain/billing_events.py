"""Builders for every message this codebase publishes to Kafka about a job's usage:

See specs/OUTBOX.md at the repository root for the outbox pair's full design. For the original
design rationale, if you have it locally, see .claude/specs/2026-09-25-generic-outbox-design.md
(local, not committed).
"""

import logging
import math
import uuid
from datetime import datetime, timezone

from core.domain.business_models import billing_name_for
from core.models import Job

logger = logging.getLogger("gateway.core.domain.billing_events")

LICENSE_FEE_METRIC_TYPE = "license"
CLASSICAL_TIME_METRIC_TYPE_PREFIX = "classical"


class BillingEvents:
    """Not a real class, just a namespace for the three message builders, so you can use BillingEvents.build_x"""

    @staticmethod
    def build_license_fee(job: Job, job_started_at: datetime | None) -> dict:
        """
        Build a license fee for a provider program. Rules:
        - The job.program, job.program.provider and job.function_size CAN'T be None (or AttributeError will be raised)
        - #1899 job_started_at can be None if the job reaches SUCCEEDED without ever passing through RUNNING
          (a direct PENDING -> SUCCEEDED transition).
        - The function size is lowercased, the billing service's metric table keys are lowercase.
        """
        metric_type = "_".join(
            [
                LICENSE_FEE_METRIC_TYPE,
                job.program.provider.name,
                job.program.title,
                job.function_size.function_size.lower(),
            ]
        )
        logger.info("job_id=%s Building license_fee message metric_type=%s", job.id, metric_type)
        return BillingEvents._envelope(
            job,
            data={
                "metric_type": metric_type,
                "metric_value": 1,
                "instance_crn": job.instance_crn,
                "resource_id": str(job.id),
                "job_started": True,
                "job_started_at": job_started_at.isoformat() if job_started_at else None,
                "job_completed": True,
                "business_model": billing_name_for(job.business_model),
            },
        )

    @staticmethod
    def build_job_usage(job: Job, job_started_at: datetime, job_last_progress_time: datetime | None) -> dict:
        """Sent when:
        - PENDING -> RUNNING: when the job starts, job_last_progress_time is None. Usage will be 0 (it just started)
        - RUNNING -> RUNNING: every 1s to update the usage in billing service. job_last_progress_time is needed
        """

        job_started = job_last_progress_time is None
        metric_type = BillingEvents._classical_metric_type(job)
        usage_seconds = 0 if job_started else BillingEvents._usage_seconds(job_started_at, job_last_progress_time)
        logger.info(
            "job_id=%s Building job_usage_event message metric_type=%s metric_value=%s job_started=%s",
            job.id,
            metric_type,
            usage_seconds,
            job_started,
        )
        return BillingEvents._envelope(
            job,
            data={
                "metric_type": metric_type,
                "metric_value": usage_seconds,
                "instance_crn": job.instance_crn,
                "resource_id": str(job.id),
                "job_started": job_started,
                "job_started_at": job_started_at.isoformat(),
                "job_completed": False,
            },
        )

    @staticmethod
    def build_job_completed_event(job: Job, job_started_at: datetime | None, job_finished_at: datetime) -> dict:
        """
        The final usage event: always built, unconditionally, on every eligible terminal
        transition, whatever the job's outcome.

        - #1899 job_started_at can be None if the job reaches any terminal state without ever passing through RUNNING
        """
        usage_seconds = BillingEvents._usage_seconds(job_started_at, job_finished_at)
        metric_type = BillingEvents._classical_metric_type(job)

        logger.info(
            "job_id=%s Building job_completed_event message metric_type=%s metric_value=%s",
            job.id,
            metric_type,
            usage_seconds,
        )
        return BillingEvents._envelope(
            job,
            data={
                "metric_type": metric_type,
                "metric_value": usage_seconds,
                "instance_crn": job.instance_crn,
                "resource_id": str(job.id),
                "job_started": False,
                "job_started_at": job_started_at.isoformat() if job_started_at else None,
                "job_completed": True,
            },
        )

    @staticmethod
    def _usage_seconds(job_started_at: datetime | None, as_of: datetime) -> int:
        """Usage in whole seconds up to as_of, rounded up so any partial second is billed. Never
        negative, even if as_of somehow precedes job_started_at (clock skew between
        processes)."""
        if job_started_at is None:
            return 0
        delta = as_of - job_started_at
        return max(0, math.ceil(delta.total_seconds()))

    @staticmethod
    def _classical_metric_type(job: Job) -> str:
        """classical_COMPUTE_PROFILE, or bare "classical" if the job has none. Shared by the two
        inline events and the outbox's final usage event: all three bill classical compute
        time."""
        parts = [CLASSICAL_TIME_METRIC_TYPE_PREFIX]
        if job.compute_profile_id:
            parts.append(job.compute_profile_id)
        return "_".join(parts)

    @staticmethod
    def _envelope(job: Job, *, data: dict) -> dict:
        """The CloudEvents 1.0 envelope shared by every message here, minus `type`."""
        return {
            "specversion": "1.0",
            "id": str(uuid.uuid4()),
            "source": "qiskit-serverless/scheduler/fleets",
            "time": datetime.now(timezone.utc).isoformat(),
            "subject": str(job.id),
            "datacontenttype": "application/json",
            "data": data,
        }
