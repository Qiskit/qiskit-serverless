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

from core.clients.iam_token_provider import get_iam_token_provider
from core.ibm_cloud import clear_cos_clients


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
