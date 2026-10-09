"""Tests for the workload payload builder. It reads the job's events, so it needs the database."""

import json
import pytest
from django.contrib.auth.models import User

from core.domain.workload_payload import build_workload_payload, map_status
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


def _simple_job(status, instance_crn=CRN):
    author, _ = User.objects.get_or_create(username="bob")
    return Job.objects.create(
        author=author,
        program=Program.objects.get_or_create(title="mine", author=author)[0],
        runner=Program.FLEETS,
        status=status,
        instance_crn=instance_crn,
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

    payload = build_workload_payload(job)

    assert payload == {
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
    assert json.loads(json.dumps(payload)) == payload  # it is stored as JSON by the next PR


def test_optional_fields_are_present_and_none_when_the_job_has_no_value_for_them():
    body = build_workload_payload(_simple_job(Job.QUEUED))["body"]

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


def test_a_job_without_instance_crn_is_rejected():
    for crn in (None, ""):
        with pytest.raises(ValueError, match="instance_crn"):
            build_workload_payload(_simple_job(Job.QUEUED, instance_crn=crn))


def test_running_at_and_ended_at_are_the_first_running_and_the_first_terminal_event():
    job = _simple_job(Job.FAILED)
    first_running = _add_status_event(job, Job.RUNNING)
    _add_status_event(job, Job.RUNNING)
    first_terminal = _add_status_event(job, Job.FAILED)
    _add_status_event(job, Job.STOPPED)

    body = build_workload_payload(job)["body"]

    assert body["running_at"] == first_running.created.isoformat()
    assert body["ended_at"] == first_terminal.created.isoformat()


def test_a_terminal_job_with_no_terminal_event_has_no_ended_at():
    job = _simple_job(Job.SUCCEEDED)
    _add_status_event(job, Job.RUNNING)

    assert build_workload_payload(job)["body"]["ended_at"] is None


def test_a_job_that_is_not_terminal_has_no_ended_at_even_if_it_has_a_terminal_event():
    job = _simple_job(Job.RUNNING)
    _add_status_event(job, Job.FAILED)

    assert build_workload_payload(job)["body"]["ended_at"] is None


def test_every_job_status_maps_and_an_unknown_one_raises():
    expected = {
        "QUEUED": "Queued",
        "PENDING": "Queued",
        "RUNNING": "Running",
        "STOPPING": "Running",
        "SUCCEEDED": "Completed",
        "FAILED": "Failed",
        "STOPPED": "Cancelled",
    }
    assert {status: map_status(status) for status in expected} == expected
    with pytest.raises(ValueError):
        map_status("EXPLODED")
