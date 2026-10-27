"""Tests for WorkloadBestEffortMirror: the best effort send of the intermediate statuses of a mirrored job."""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.db.utils import InterfaceError, OperationalError
from prometheus_client import REGISTRY

from core.models import Job, Program, WorkloadMirror
from core.services import workload_best_effort_mirror
from core.services.background_executor import BackgroundExecutorNotInitializedError, BackgroundPool
from core.services.workload_best_effort_mirror import NoOpWorkloadMirror, WorkloadBestEffortMirror

pytestmark = pytest.mark.django_db

CRN = "crn:v1:bluemix:public:quantum-computing:us-east:a/acct:inst::"
MODULE = "core.services.workload_best_effort_mirror"


@pytest.fixture
def executor():
    mock = MagicMock()
    mock.would_accept.return_value = True
    with patch(f"{MODULE}.get_background_executor", return_value=mock):
        yield mock


@pytest.fixture
def client():
    with patch(f"{MODULE}.get_functions_operator_client") as get_client:
        yield get_client.return_value


@pytest.fixture
def build():
    with patch(f"{MODULE}.build_workload_payload") as mock:
        mock.return_value = {"function_id": "fid", "body": {"crn": CRN}}
        yield mock


def _job(status=Job.PENDING, mirrored=True, filler=False):
    author, _ = User.objects.get_or_create(username="bob")
    job = Job.objects.create(
        author=author,
        program=Program.objects.get_or_create(title="mine", author=author)[0],
        runner=Program.FLEETS,
        status=status,
        instance_crn=CRN,
        filler=filler,
    )
    if mirrored:
        WorkloadMirror.objects.create(job=job)
    return job


def _count(status, outcome):
    return REGISTRY.get_sample_value("workload_best_effort_mirror_total", {"status": status, "outcome": outcome})


def test_a_filler_job_costs_no_query_and_sends_nothing(executor, build, django_assert_num_queries):
    job = _job(filler=True)

    with django_assert_num_queries(0):
        WorkloadBestEffortMirror().send(job)

    executor.submit.assert_not_called()


def test_a_job_without_a_mirror_row_sends_nothing(executor, build):
    WorkloadBestEffortMirror().send(_job(mirrored=False))

    executor.submit.assert_not_called()


@pytest.mark.parametrize(
    "job_status, status",
    [(Job.PENDING, "Pending"), (Job.RUNNING, "Running"), (Job.STOPPING, "Stopping")],
)
def test_happy_path_submits_the_envelope_and_the_task_puts_it(
    executor, client, django_assert_num_queries, job_status, status
):
    job = _job(job_status)
    sent_before = _count(status, "sent")

    WorkloadBestEffortMirror().send(job)

    executor.submit.assert_called_once()
    call = executor.submit.call_args
    assert call.args[:2] == (BackgroundPool.RUNTIME_API, workload_best_effort_mirror._put_background_task)
    function_id, body, sent_status = call.args[2:]
    assert function_id == str(job.id)
    assert body["status"] == status
    assert sent_status == status
    assert call.kwargs == {"replace_key": f"job:{job.id}"}
    executor.would_accept.assert_called_once_with(BackgroundPool.RUNTIME_API, f"job:{job.id}")

    with django_assert_num_queries(0):
        workload_best_effort_mirror._put_background_task(function_id, body, sent_status)

    client.put_function.assert_called_once_with(function_id, body, timeout=3)
    assert _count(status, "sent") == sent_before + 1


def test_a_full_pool_drops_before_building_the_payload(executor, build):
    executor.would_accept.return_value = False
    job = _job(Job.STOPPING)
    before = _count("Stopping", "dropped")

    WorkloadBestEffortMirror().send(job)

    build.assert_not_called()
    executor.submit.assert_not_called()
    assert _count("Stopping", "dropped") == before + 1


def test_a_rejected_submit_counts_dropped(executor, build):
    executor.submit.return_value = None
    before = _count("Pending", "dropped")

    WorkloadBestEffortMirror().send(_job())

    assert _count("Pending", "dropped") == before + 1


def test_a_payload_error_is_swallowed_and_counted_failed(executor, build):
    build.side_effect = ValueError("no program")
    before = _count("Pending", "failed")

    WorkloadBestEffortMirror().send(_job())

    executor.submit.assert_not_called()
    assert _count("Pending", "failed") == before + 1


def test_an_uninitialized_executor_propagates_and_is_not_counted(executor, build):
    executor.would_accept.side_effect = BackgroundExecutorNotInitializedError("no init")
    before = _count("Pending", "failed")

    with pytest.raises(BackgroundExecutorNotInitializedError):
        WorkloadBestEffortMirror().send(_job())

    assert _count("Pending", "failed") == before


def test_the_task_swallows_a_put_failure_and_counts_failed(client):
    client.put_function.side_effect = RuntimeError("boom")
    before = _count("Running", "failed")

    workload_best_effort_mirror._put_background_task("fid", {"crn": CRN}, "Running")

    assert _count("Running", "failed") == before + 1


def test_a_database_outage_propagates_from_any_step(executor, build):
    job = _job()

    with patch(f"{MODULE}.is_mirrored", side_effect=OperationalError("down")), pytest.raises(OperationalError):
        WorkloadBestEffortMirror().send(job)

    build.side_effect = OperationalError("down")
    with pytest.raises(OperationalError):
        WorkloadBestEffortMirror().send(job)

    build.side_effect = InterfaceError("down")
    with pytest.raises(InterfaceError):
        WorkloadBestEffortMirror().send(job)


def test_the_no_op_mirror_touches_nothing(executor, django_assert_num_queries):
    job = _job()

    with django_assert_num_queries(0):
        NoOpWorkloadMirror().send(job)

    executor.would_accept.assert_not_called()
    executor.submit.assert_not_called()
