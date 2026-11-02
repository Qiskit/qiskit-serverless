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

"""Global pytest fixtures for gateway tests."""

from unittest.mock import patch

import pytest
from django.core.cache import cache

from core.clients.iam_token_provider import get_iam_token_provider
from core.config_key import ConfigKey
from core.models import Config
from core.ibm_cloud import clear_cos_clients

from tests.utils import TestUtils


@pytest.fixture
def default_ce_project(settings, db):
    """Wire up the deployment infra so a Fleets-default function is runnable.

    Request this in run-path tests that are not about a specific runner: they create a function
    with ``TestUtils.create_program`` (now Fleets by default, like production) and then run it, so
    the function needs an active default CE project, a default size, and the Fleets argument
    storage stubbed out (enqueueing a Fleets job writes its arguments to COS, which a unit test
    must not reach). ``create_program`` (via ``make_fleets_program_runnable``) assigns the project
    and size once this fixture has registered the default project and the default compute profile.
    Returns the project for tests that need the handle.
    """
    from core.models import ComputeProfile  # pylint: disable=import-outside-toplevel

    settings.CE_DEFAULT_PROJECT_NAME = "default-ce-project"
    ComputeProfile.objects.get_or_create(compute_profile_id=settings.DEFAULT_FUNCTION_SIZE_PROFILE)
    project = TestUtils.get_or_create_ce_project(
        project_name="default-ce-project",
        project_id="ce-proj-id",
        cos_bucket_user_data_name="user-bucket",
        cos_bucket_provider_data_name="provider-bucket",
        cos_instance_name="cos-instance",
        cos_key_name="cos-key",
    )
    TestUtils._provision_fleets_programs = True
    try:
        with patch("core.services.storage.arguments_storage_fleets.FleetsArgumentsStorage.save"):
            yield project
    finally:
        TestUtils._provision_fleets_programs = False


@pytest.fixture(autouse=True)
def media_root_tmp(tmp_path, settings):
    """Redirect MEDIA_ROOT to a temp directory for every test.

    Prevents PathBuilder.absolute_path() from creating directories inside
    the source tree (gateway/media/) during test runs.
    """
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.fixture(autouse=True)
def clear_django_cache():
    """Clear the process-wide Django cache before every test.

    `django_db` rolls back the database between tests, but Django's cache (e.g. the admin
    dashboard's cached recent-Fleets-jobs timeline) is not tied to that transaction and would
    otherwise leak a value cached by one test into the next.
    """
    cache.clear()


@pytest.fixture(autouse=True)
def job_creation_config(request):
    """The use case that creates a job reads the workload mirror flag and the active job limit, so every test that uses
    the database starts with their Config rows there, the mirror off and the limit at 50. A test that needs another
    value sets it with Config.set."""
    if request.node.get_closest_marker("django_db") or "db" in request.fixturenames:
        request.getfixturevalue("db")
        for key, value in ((ConfigKey.WORKLOADS_MIRROR_ENABLED, "false"), (ConfigKey.ACTIVE_JOBS_PER_USER, "50")):
            Config.objects.get_or_create(name=key.value, defaults={"value": value, "description": "test"})


@pytest.fixture(autouse=True)
def blocked_jobs_stop_disabled(request):
    """A run request reads the blocked resources flag, so every test that uses the database starts with its Config
    row there, off. A test that needs it on sets it with Config.set."""
    if request.node.get_closest_marker("django_db") or "db" in request.fixturenames:
        request.getfixturevalue("db")
        Config.objects.get_or_create(
            name=ConfigKey.BLOCKED_JOBS_STOP_ENABLED.value, defaults={"value": "false", "description": "test"}
        )
        # Read whenever a job is checked against blocked_cloud_resources
        Config.objects.get_or_create(
            name=ConfigKey.BLOCKED_RESOURCES_REGIONAL.value, defaults={"value": "true", "description": "test"}
        )


@pytest.fixture(autouse=True)
def program_timeout_hours_default(request):
    """check_job_timeout reads the program timeout from Config, so every test that uses the database starts
    with its Config row there, at the 24h default. A test that needs another value sets it with Config.set."""
    if request.node.get_closest_marker("django_db") or "db" in request.fixturenames:
        request.getfixturevalue("db")
        Config.objects.get_or_create(
            name=ConfigKey.PROGRAM_TIMEOUT_HOURS.value, defaults={"value": "24", "description": "test"}
        )


@pytest.fixture(autouse=True)
def clear_iam_token_providers():
    """Clear the shared IAM token provider cache before every test.

    The cache is keyed on (api_key, iam_url), and the provider tests all build with the same
    dummy key, so one test's patched provider would otherwise serve the next one.
    """
    get_iam_token_provider.cache_clear()


@pytest.fixture(autouse=True)
def clear_cos_client_cache():
    """Clear the per-process COS client cache before every test."""
    clear_cos_clients()
