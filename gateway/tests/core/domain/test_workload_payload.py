"""Tests for the workload payload builder. It reads the job's events, so it needs the database."""

from datetime import datetime

import pytest
from django.contrib.auth.models import User

from core.domain.workload_payload import _iso, build_workload_payload, map_status
from core.model_managers.job_events import JobEventContext, JobEventOrigin
from core.models import ComputeProfile, FunctionSize, Job, JobEvent, Program, Provider

CRN = "crn:v1:bluemix:public:quantum-computing:us-east:a/acct:inst::"

pytestmark = pytest.mark.django_db


def _add_status_event(job, status):
    return JobEvent.objects.add_status_event(
        job_id=job.id,
        origin=JobEventOrigin.SCHEDULER,
        context=JobEventContext.UPDATE_JOB_STATUS,
        status=status,
    )


def test_builds_the_full_envelope_for_a_finished_job():
    alice = User.objects.create_user(username="alice")
    provider = Provider.objects.create(name="ibm")
    program = Program.objects.create(title="sampler", provider=provider, author=alice)
    profile = ComputeProfile.objects.create(compute_profile_id="16x128", cpu="16", memory="128")
    size = FunctionSize.objects.create(function=program, function_size="m", compute_profile=profile)
    job = Job.objects.create(
        author=alice,
        program=program,
        runner=Program.FLEETS,
        status=Job.SUCCEEDED,
        instance_crn=CRN,
        compute_profile_fk=profile,
        function_size=size,
    )
    running = _add_status_event(job, Job.RUNNING)
    ended = _add_status_event(job, Job.SUCCEEDED)

    assert build_workload_payload(job) == {
        "function_id": str(job.id),
        "body": {
            "name": "sampler",
            "provider": "ibm",
            "crn": CRN,
            "user_id": "alice",
            "status": "Completed",
            "compute_profile": "16x128",
            "size": "M",
            "created_at": job.created.isoformat(),
            "running_at": running.created.isoformat(),
            "ended_at": ended.created.isoformat(),
        },
    }


def test_optional_fields_are_present_and_none_when_the_job_has_no_value_for_them():
    bob = User.objects.create_user(username="bob")
    job = Job.objects.create(
        author=bob,
        program=Program.objects.create(title="mine", provider=None, author=bob),
        runner=Program.FLEETS,
        status=Job.QUEUED,
    )

    body = build_workload_payload(job)["body"]

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


def test_a_naive_datetime_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        _iso(datetime(2026, 10, 8, 10, 5, 0))
