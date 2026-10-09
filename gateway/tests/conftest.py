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

import pytest
from django.core.cache import cache

from core.config_key import ConfigKey
from core.models import Config


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
def workloads_mirror_off(request):
    """The use case that creates a job and the job transitions read the workload mirror flag, so every test that
    uses the database starts with its Config row there, off. A test that needs it on sets it with Config.set."""
    if request.node.get_closest_marker("django_db") or "db" in request.fixturenames:
        request.getfixturevalue("db")
        Config.objects.get_or_create(
            name=ConfigKey.WORKLOADS_MIRROR_ENABLED.value, defaults={"value": "false", "description": "test"}
        )
