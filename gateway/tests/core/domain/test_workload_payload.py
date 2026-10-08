"""Unit tests for the workload payload builder. Pure, in memory, no database."""

from datetime import datetime, timezone

import pytest
from django.contrib.auth.models import User

from core.domain.workload_payload import build_workload_payload, map_status
from core.models import FunctionSize, Job, Program, Provider

CRN = "crn:v1:bluemix:public:quantum-computing:us-east:a/acct:inst::"
CREATED = datetime(2026, 10, 8, 10, 0, 0, tzinfo=timezone.utc)
STARTED = datetime(2026, 10, 8, 10, 1, 0, tzinfo=timezone.utc)
ENDED = datetime(2026, 10, 8, 10, 5, 0, tzinfo=timezone.utc)


def _job(**overrides) -> Job:
    defaults = dict(
        author=User(username="alice"),
        program=Program(title="sampler", provider=Provider(name="ibm")),
        instance_crn=CRN,
        compute_profile_fk_id="16x128",
        function_size=FunctionSize(function_size="m"),
        created=CREATED,
        running_started_at=STARTED,
    )
    defaults.update(overrides)
    return Job(**defaults)


def test_builds_the_full_envelope_for_a_finished_job():
    job = _job()

    assert build_workload_payload(job, Job.SUCCEEDED, ENDED) == {
        "function_id": str(job.id),
        "body": {
            "name": "sampler",
            "provider": "ibm",
            "crn": CRN,
            "user_id": "alice",
            "status": "Completed",
            "compute_profile": "16x128",
            "size": "M",
            "created_at": CREATED.isoformat(),
            "running_at": STARTED.isoformat(),
            "ended_at": ENDED.isoformat(),
        },
    }


def test_optional_fields_are_present_and_none_when_the_job_has_no_value_for_them():
    job = _job(
        program=Program(title="mine", provider=None),
        function_size=None,
        running_started_at=None,
        compute_profile_fk_id=None,
    )

    body = build_workload_payload(job, Job.QUEUED, None)["body"]

    assert body["status"] == "Queued"
    assert set(body) == {
        "name",
        "provider",
        "crn",
        "user_id",
        "status",
        "compute_profile",
        "size",
        "created_at",
        "running_at",
        "ended_at",
    }
    assert [body[k] for k in ("provider", "compute_profile", "size", "running_at", "ended_at")] == [None] * 5


def test_every_job_status_maps_and_an_unknown_one_raises():
    statuses = (Job.QUEUED, Job.PENDING, Job.RUNNING, Job.STOPPING, Job.SUCCEEDED, Job.FAILED, Job.STOPPED)
    assert {s: map_status(s) for s in statuses} == {
        Job.QUEUED: "Queued",
        Job.PENDING: "Queued",
        Job.RUNNING: "Running",
        Job.STOPPING: "Running",
        Job.SUCCEEDED: "Completed",
        Job.FAILED: "Failed",
        Job.STOPPED: "Cancelled",
    }
    with pytest.raises(ValueError):
        map_status("EXPLODED")
