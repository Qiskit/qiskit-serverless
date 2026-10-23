"""Query-count guards for the main list/lookup paths, so N+1s do not come back.

Each test measures the same call with few and with many rows and asserts the number of queries is equal.
"""

import pytest
from django.contrib.auth.models import User
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import CodeEngineProject, ComputeProfile, FunctionSize, Job, JobConfig, Program, Provider
from tests.utils import TestUtils

pytestmark = pytest.mark.django_db

LEGACY = FunctionAccessResult(use_legacy_authorization=True)


@pytest.fixture
def world():
    owner = User.objects.create_user(username="qc-owner")
    admin, group = TestUtils.add_user_to_group("qc-admin", "qc-admins")
    project = CodeEngineProject.objects.create(project_name="qc", project_id="qc", region="eu-de")
    provider = Provider.objects.create(name="qc-provider", code_engine_project=project)
    provider.admin_groups.add(group)
    profile = ComputeProfile.objects.create(compute_profile_id="8x32", cpu="8", memory="32")
    function = Program.objects.create(
        title="qc-fn", author=owner, provider=provider, code_engine_project=project, runner=Program.FLEETS
    )
    size = FunctionSize.objects.create(function=function, function_size="S", compute_profile=profile)
    function.default_size = size
    function.save()
    return {
        "owner": owner,
        "admin": admin,
        "provider": provider,
        "profile": profile,
        "function": function,
        "size": size,
        "config": JobConfig.objects.create(workers=2),
    }


def _add_jobs(world, count, status=Job.QUEUED):
    for _ in range(count):
        Job.objects.create(
            author=world["owner"],
            program=world["function"],
            runner=Program.FLEETS,
            status=status,
            compute_profile_fk=world["profile"],
            function_size=world["size"],
            function_size_name="S",  # set by run() when the job is created
            config=world["config"],
        )


def _add_functions(world, count):
    for index in range(count):
        function = Program.objects.create(
            title=f"qc-extra-{Program.objects.count()}-{index}", author=world["owner"], provider=world["provider"]
        )
        function.default_size = FunctionSize.objects.create(
            function=function, function_size="S", compute_profile=world["profile"]
        )
        function.save()


def _count(call):
    with CaptureQueriesContext(connection) as ctx:
        response = call()
    assert response.status_code == 200, response.content[:200]
    return len(ctx)


def _get(user, url, **params):
    client = APIClient()
    TestUtils.authorize_client(user=user, client=client, accessible_functions=LEGACY)
    return lambda: client.get(url, params)


def test_jobs_list_is_flat(world):
    _add_jobs(world, 2)
    few = _count(_get(world["owner"], reverse("v1:jobs-list"), limit=100))
    _add_jobs(world, 20)
    assert _count(_get(world["owner"], reverse("v1:jobs-list"), limit=100)) == few


def test_provider_jobs_list_is_flat(world):
    _add_jobs(world, 2)
    call = lambda: _get(world["admin"], reverse("v1:jobs-provider-list"), provider="qc-provider", limit=100)
    few = _count(call())
    _add_jobs(world, 20)
    assert _count(call()) == few


def test_program_jobs_is_flat(world):
    url = reverse("v1:programs-get-jobs", args=[world["function"].id])
    _add_jobs(world, 2)
    few = _count(_get(world["admin"], url))
    _add_jobs(world, 20)
    assert _count(_get(world["admin"], url)) == few


def test_programs_list_is_flat(world):
    call = lambda: _get(world["owner"], reverse("v1:programs-list"))
    few = _count(call())
    _add_functions(world, 15)
    assert _count(call()) == few


def test_scheduler_loop_loads_relations_in_the_query(world):
    from scheduler.schedule import get_jobs_to_schedule_fair_share  # pylint: disable=import-outside-toplevel

    _add_jobs(world, 3)
    jobs = list(get_jobs_to_schedule_fair_share(slots=5, gpu=False, runner=Program.FLEETS))
    assert jobs
    with CaptureQueriesContext(connection) as ctx:
        for job in jobs:
            _ = (job.author.id, job.program.title, job.program.provider.name, job.program.code_engine_project)
    assert len(ctx) == 0


def test_running_jobs_loop_loads_relations_in_the_query(world):
    """Guards the relation loads only. update_job_status is replaced."""
    from unittest.mock import MagicMock  # pylint: disable=import-outside-toplevel

    _add_jobs(world, 5, status=Job.RUNNING)
    with CaptureQueriesContext(connection) as ctx:
        from scheduler.tasks.update_fleets_jobs_statuses import (  # pylint: disable=import-outside-toplevel
            UpdateFleetsJobsStatuses,
        )

        seen = []

        def read_what_a_pass_reads(polled):
            job = polled.job
            seen.append((job.program.provider.name, job.program.code_engine_project.project_name, job.size_label))
            return False

        task = UpdateFleetsJobsStatuses.__new__(UpdateFleetsJobsStatuses)
        task.kill_signal = type("K", (), {"received": False})()
        task.metrics = MagicMock()
        task.update_job_status = read_what_a_pass_reads
        task.run()
    assert len(seen) == 5
    assert len(ctx) == 1


def test_scheduler_context_loads_author_program_provider_project_and_config(world):
    _add_jobs(world, 4, status=Job.RUNNING)
    jobs = list(Job.objects.filter(status=Job.RUNNING).with_scheduler_context())
    assert len(jobs) == 4
    with CaptureQueriesContext(connection) as ctx:
        for job in jobs:
            _ = (job.author.id, job.program.provider.name, job.program.code_engine_project.project_name)
            assert job.config.workers == 2
    assert len(ctx) == 0


def test_with_program_loads_program_and_provider(world):
    _add_jobs(world, 4)
    jobs = list(Job.objects.with_program())
    with CaptureQueriesContext(connection) as ctx:
        for job in jobs:
            _ = (job.program.title, job.program.provider.name)
    assert len(ctx) == 0


def test_a_real_status_pass_reads_no_events_per_job(world):
    """A full pass over jobs that stay RUNNING is one query, however many jobs there are."""
    from unittest.mock import MagicMock, patch  # pylint: disable=import-outside-toplevel

    from core.models import JobEvent  # pylint: disable=import-outside-toplevel
    from core.services.job_transitions import JobTransitionService  # pylint: disable=import-outside-toplevel
    from scheduler.tasks.update_fleets_jobs_statuses import (  # pylint: disable=import-outside-toplevel
        UpdateFleetsJobsStatuses,
    )

    def add_running(count):
        _add_jobs(world, count, status=Job.RUNNING)
        for job in Job.objects.filter(job_events__isnull=True):
            JobEvent.objects.add_status_event(job_id=job.id, origin="API", context="RUN_PROGRAM", status=Job.RUNNING)
        Job.objects.update(fleet_id="fleet")

    def one_pass():
        task = UpdateFleetsJobsStatuses(
            kill_signal=MagicMock(received=False),
            metrics=MagicMock(),
            transitions=JobTransitionService(sender=MagicMock()),
        )
        runner = MagicMock()
        runner.status.return_value = Job.RUNNING
        with patch("scheduler.tasks.update_fleets_jobs_statuses.get_runner", return_value=runner):
            with CaptureQueriesContext(connection) as ctx:
                task.run()
        return len(ctx)

    add_running(2)
    few = one_pass()
    add_running(20)
    assert one_pass() == few == 1


def test_a_blocked_jobs_pass_is_flat_and_loads_what_a_stop_reads(world):
    """A blocked-jobs pass is two queries (blocked rows, then jobs), however many jobs there are."""
    from unittest.mock import MagicMock  # pylint: disable=import-outside-toplevel

    from core.config_key import ConfigKey  # pylint: disable=import-outside-toplevel
    from core.models import BlockedCloudResource, Config  # pylint: disable=import-outside-toplevel
    from scheduler.tasks.stop_blocked_fleets_jobs import (  # pylint: disable=import-outside-toplevel
        StopBlockedFleetsJobs,
    )

    Config.add_defaults()
    BlockedCloudResource.objects.create(account="acct", plan="plan", subscription="sub")
    seen = []

    def add_blocked(count):
        _add_jobs(world, count, status=Job.RUNNING)
        Job.objects.update(account_id="acct", plan_id="plan", subscription_id="sub")

    def one_pass():
        task = StopBlockedFleetsJobs(kill_signal=MagicMock(received=False), canceller=MagicMock())
        task.canceller.paused.return_value = False

        def read_what_a_stop_reads(job, **_):
            seen.append(
                (job.author.username, job.program.provider.name, job.program.code_engine_project, job.size_label)
            )
            return True

        task.canceller.cancel.side_effect = read_what_a_stop_reads
        Config.get_bool(ConfigKey.BLOCKED_JOBS_STOP_ENABLED)  # warm the config cache, as on a running scheduler
        with CaptureQueriesContext(connection) as ctx:
            task.run()
        return len(ctx)

    add_blocked(2)
    few = one_pass()
    add_blocked(20)
    assert one_pass() == few == 2
    assert len(seen) == 2 + 22

    # nothing blocked: only the blocked rows are read, no job query
    BlockedCloudResource.objects.all().delete()
    seen.clear()
    assert one_pass() == 1
    assert not seen
