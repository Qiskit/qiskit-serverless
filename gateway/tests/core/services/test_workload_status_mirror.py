"""Tests for WorkloadStatusMirror: the best effort send of the intermediate statuses of a mirrored job."""

import logging
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db.utils import IntegrityError, InterfaceError, OperationalError
from prometheus_client import REGISTRY

from core.config_key import ConfigKey
from core.domain.workload_payload import _STATUS
from core.models import Config, Job, Program, WorkloadMirror
from core.services import workload_status_mirror
from core.services.background_executor import BackgroundExecutorNotInitializedError, BackgroundPool
from core.services.workload_status_mirror import WorkloadStatusMirror

pytestmark = pytest.mark.django_db

CRN = "crn:v1:bluemix:public:quantum-computing:us-east:a/acct:inst::"
MODULE = "core.services.workload_status_mirror"


@pytest.fixture(autouse=True)
def switch_on():
    Config.add_defaults()
    Config.set(ConfigKey.WORKLOADS_STATUS_UPDATES_ENABLED, "true")


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
    return REGISTRY.get_sample_value("workload_status_mirror_total", {"status": status, "outcome": outcome})


def test_kill_switch_off_builds_and_submits_nothing(executor, build):
    Config.set(ConfigKey.WORKLOADS_STATUS_UPDATES_ENABLED, "false")

    WorkloadStatusMirror().send(_job())

    build.assert_not_called()
    executor.submit.assert_not_called()


def test_a_filler_job_costs_no_query_and_sends_nothing(executor, build, django_assert_num_queries):
    job = _job(filler=True)

    with django_assert_num_queries(0):
        WorkloadStatusMirror().send(job)

    executor.submit.assert_not_called()


def test_a_job_without_a_mirror_row_sends_nothing(executor, build):
    WorkloadStatusMirror().send(_job(mirrored=False))

    executor.submit.assert_not_called()


def test_happy_path_submits_the_envelope_and_the_task_puts_it(executor, client, django_assert_num_queries):
    job = _job(Job.RUNNING)
    sent_before = _count("Running", "sent")

    WorkloadStatusMirror().send(job)

    executor.submit.assert_called_once()
    call = executor.submit.call_args
    assert call.args[:2] == (BackgroundPool.RUNTIME_API, workload_status_mirror._put)
    function_id, body, status = call.args[2:]
    assert function_id == str(job.id)
    assert body["status"] == "Running"
    assert status == "Running"
    assert call.kwargs == {"replace_key": f"job:{job.id}"}
    executor.would_accept.assert_called_once_with(BackgroundPool.RUNTIME_API, f"job:{job.id}")

    with django_assert_num_queries(0):
        workload_status_mirror._put(function_id, body, status)

    client.put_function.assert_called_once_with(function_id, body, timeout=3)
    assert _count("Running", "sent") == sent_before + 1


def test_a_full_pool_drops_before_building_the_payload(executor, build):
    executor.would_accept.return_value = False
    job = _job(Job.STOPPING)
    before = _count(_STATUS[job.status], "dropped")

    WorkloadStatusMirror().send(job)

    build.assert_not_called()
    executor.submit.assert_not_called()
    assert _count("Stopping", "dropped") == before + 1


def test_a_rejected_submit_counts_dropped(executor, build):
    executor.submit.return_value = None
    before = _count("Pending", "dropped")

    WorkloadStatusMirror().send(_job())

    assert _count("Pending", "dropped") == before + 1


def test_a_payload_error_is_swallowed_and_counted_failed(executor, build):
    build.side_effect = ValueError("no program")
    before = _count("Pending", "failed")

    WorkloadStatusMirror().send(_job())

    executor.submit.assert_not_called()
    assert _count("Pending", "failed") == before + 1


def test_an_uninitialized_executor_is_swallowed_and_logged_as_error(executor, build, caplog):
    executor.would_accept.side_effect = BackgroundExecutorNotInitializedError("no init")

    with caplog.at_level(logging.ERROR):
        WorkloadStatusMirror().send(_job())

    assert any(record.levelno == logging.ERROR for record in caplog.records)


def test_the_task_swallows_a_put_failure_and_counts_failed(client):
    client.put_function.side_effect = RuntimeError("boom")
    before = _count("Running", "failed")

    workload_status_mirror._put("fid", {"crn": CRN}, "Running")

    assert _count("Running", "failed") == before + 1


@pytest.mark.parametrize("error", [OperationalError, InterfaceError])
@pytest.mark.parametrize("where", ["config", "is_mirrored", "would_accept", "build"])
def test_a_database_outage_propagates_from_every_step(executor, build, error, where):
    job = _job()
    targets = {
        "config": patch(f"{MODULE}.Config.get_bool", side_effect=error("down")),
        "is_mirrored": patch(f"{MODULE}.is_mirrored", side_effect=error("down")),
        "would_accept": patch.object(executor, "would_accept", side_effect=error("down")),
        "build": patch.object(build, "side_effect", error("down")),
    }

    with targets[where], pytest.raises(error):
        WorkloadStatusMirror().send(job)


def test_another_database_error_is_swallowed_and_counted_failed(executor, build):
    build.side_effect = IntegrityError("constraint")
    before = _count("Pending", "failed")

    WorkloadStatusMirror().send(_job())

    assert _count("Pending", "failed") == before + 1


def test_a_missing_config_row_is_treated_as_switch_off(executor, build):
    Config.objects.filter(name=ConfigKey.WORKLOADS_STATUS_UPDATES_ENABLED.value).delete()
    cache.clear()

    WorkloadStatusMirror().send(_job())

    executor.submit.assert_not_called()


def test_a_job_in_a_terminal_status_counts_nothing_under_any_label(executor, build):
    def series():
        return {
            (sample.labels["status"], sample.labels["outcome"]): sample.value
            for metric in REGISTRY.collect()
            if metric.name == "workload_status_mirror"
            for sample in metric.samples
            if sample.name.endswith("_total")
        }

    before = series()
    executor.submit.return_value = None

    WorkloadStatusMirror().send(_job(Job.SUCCEEDED))

    assert series() == before
    assert {status for status, _ in before} == {"Pending", "Running", "Stopping"}
