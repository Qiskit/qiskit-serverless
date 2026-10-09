"""Query-count guards for the main list/lookup paths, so N+1s do not come back.

Each test measures the same call with few and with many rows and asserts the number of queries is equal.
"""

import pytest
from django.contrib.auth.models import Group, User
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import CodeEngineProject, ComputeProfile, FunctionSize, Job, Program, Provider
from tests.utils import TestUtils

pytestmark = pytest.mark.django_db

LEGACY = FunctionAccessResult(use_legacy_authorization=True)


@pytest.fixture
def world():
    owner = User.objects.create_user(username="qc-owner")
    admin = User.objects.create_user(username="qc-admin")
    group = Group.objects.create(name="qc-admins")
    admin.groups.add(group)
    project = CodeEngineProject.objects.create(project_name="qc", project_id="qc", region="eu-de")
    provider = Provider.objects.create(name="qc-provider", code_engine_project=project)
    provider.admin_groups.add(group)
    profile = ComputeProfile.objects.create(compute_profile_id="8x32", cpu="8", memory="32")
    function = Program.objects.create(title="qc-fn", author=owner, provider=provider, runner=Program.FLEETS)
    size = FunctionSize.objects.create(function=function, function_size="S", compute_profile=profile)
    function.default_size = size
    function.save()
    return {"owner": owner, "admin": admin, "provider": provider, "profile": profile, "function": function}


def _add_jobs(world, count, status=Job.QUEUED):
    for _ in range(count):
        Job.objects.create(
            author=world["owner"],
            program=world["function"],
            runner=Program.FLEETS,
            status=status,
            compute_profile_fk=world["profile"],
        )


def _add_functions(world, count):
    for index in range(count):
        function = Program.objects.create(
            title=f"qc-extra-{Program.objects.count()}-{index}", author=world["owner"], provider=world["provider"]
        )
        FunctionSize.objects.create(function=function, function_size="S", compute_profile=world["profile"])


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
    _add_jobs(world, 5, status=Job.RUNNING)
    with CaptureQueriesContext(connection) as ctx:
        from scheduler.tasks.update_fleets_jobs_statuses import (  # pylint: disable=import-outside-toplevel
            UpdateFleetsJobsStatuses,
        )

        seen = []
        task = UpdateFleetsJobsStatuses.__new__(UpdateFleetsJobsStatuses)
        task.kill_signal = type("K", (), {"received": False})()
        task.update_job_status = lambda job: seen.append((job.author.id, job.program.provider.name)) or False
        task.run()
    assert len(seen) == 5
    assert len(ctx) == 1
