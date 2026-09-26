"""Builders for the two billing facts that flow through the outbox: the provider license fee
and the job's final usage event. Each returns the Kafka message body exactly as it will be sent.

Neither builder queries the database: `running_started_at` is a parameter because
Job.change_status already needs to query it once (JobEvent.objects.first_running_at) to decide
license fee eligibility, and there is no reason to query it twice. Neither builder knows about
Kafka transport either: CloudEvents' own `type` field (which equals the Kafka topic name) is
added later, by KafkaOutboxSender at send time, not here.

See specs/OUTBOX.md at the repository root for the full design. For the original design
rationale, if you have it locally, see .claude/specs/2026-09-25-generic-outbox-design.md
(local, not committed).
"""

import logging
import math
import uuid
from datetime import datetime, timezone

from core.domain.business_models import billing_name_for
from core.models import Job, JobEvent

logger = logging.getLogger("gateway.core.domain.billing_events")

LICENSE_FEE_METRIC_TYPE = "license"
CLASSICAL_TIME_METRIC_TYPE_PREFIX = "classical"


def _usage_seconds(running_started_at: datetime | None, as_of: datetime) -> int:
    """Usage in whole seconds up to as_of, rounded up so any partial second is billed. Never
    negative, even if as_of somehow precedes running_started_at (clock skew between processes)."""
    if running_started_at is None:
        return 0
    delta = as_of - running_started_at
    return max(0, math.ceil(delta.total_seconds()))


def _envelope(job: Job, *, data: dict) -> dict:
    """The CloudEvents 1.0 envelope shared by both messages, minus `type`."""
    return {
        "specversion": "1.0",
        "id": str(uuid.uuid4()),
        "source": "qiskit-serverless/scheduler/fleets",
        "time": datetime.now(timezone.utc).isoformat(),
        "subject": str(job.id),
        "datacontenttype": "application/json",
        "data": data,
    }


def build_billing_event_message(job: Job, event: JobEvent, running_started_at: datetime | None) -> dict:
    """The final usage event: always built, whatever the job's terminal status. Reports zero
    seconds for a job that never ran (_usage_seconds already handles running_started_at=None)."""
    usage_seconds = _usage_seconds(running_started_at, event.created)
    metric_type_parts = [CLASSICAL_TIME_METRIC_TYPE_PREFIX]
    if job.compute_profile:
        metric_type_parts.append(job.compute_profile)
    metric_type = "_".join(metric_type_parts)

    logger.info(
        "job_id=%s Building billing_event message metric_type=%s metric_value=%s",
        job.id,
        metric_type,
        usage_seconds,
    )
    return _envelope(
        job,
        data={
            "metric_type": metric_type,
            "metric_value": usage_seconds,
            "instance_crn": job.instance_crn,
            "resource_id": str(job.id),
            "job_started": False,
            "job_started_at": running_started_at.isoformat() if running_started_at else None,
            "job_completed": True,
        },
    )


def build_license_fee_message(job: Job, event: JobEvent, running_started_at: datetime | None) -> dict | None:
    """The provider license fee. Callers must only call this once they have already decided the
    job ran (see Job.change_status): this function does not repeat that check.

    Returns None silently when the function has no provider, or when its Program has itself been
    deleted (SET_NULL) so having a provider can no longer even be checked (the normal case for
    most jobs either way). Returns None after logging an error only when the Program and its
    provider are both still there but FunctionSize is missing (a SET_NULL deletion racing the
    transition, made rare, not impossible, by building here instead of at send time). That last
    case is an anomaly worth a log line; the others are not.
    """
    # pylint: disable=unused-argument
    if job.program is None or job.program.provider is None:
        return None

    if job.function_size is None:
        logger.error(
            "job_id=%s license fee message cannot be built: function_size is missing although "
            "the function has a provider, waiving the fee",
            job.id,
        )
        return None

    metric_type = "_".join(
        [LICENSE_FEE_METRIC_TYPE, job.program.provider.name, job.program.title, job.function_size.function_size]
    )
    logger.info("job_id=%s Building license_fee message metric_type=%s", job.id, metric_type)
    return _envelope(
        job,
        data={
            "metric_type": metric_type,
            "metric_value": 1,
            "instance_crn": job.instance_crn,
            "resource_id": str(job.id),
            "job_started": True,
            "job_started_at": running_started_at.isoformat() if running_started_at else None,
            "job_completed": True,
            "business_model": billing_name_for(job.business_model),
        },
    )
