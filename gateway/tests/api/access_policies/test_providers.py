"""Tests for access policies."""

import pytest

from django.contrib.auth.models import Group, User

from api.access_policies.providers import ProviderAccessPolicy
from api.domain.authorization.function_access_entry import FunctionAccessEntry
from api.domain.authorization.function_access_result import FunctionAccessResult
from core.models import (
    Job,
    PLATFORM_PERMISSION_JOB_READ,
    PLATFORM_PERMISSION_PROVIDER_FILES,
    PLATFORM_PERMISSION_PROVIDER_JOBS,
    PLATFORM_PERMISSION_PROVIDER_LOGS,
    PLATFORM_PERMISSION_PROVIDER_UPLOAD,
    Provider,
)

pytestmark = pytest.mark.django_db


def _entry(provider_name, permissions):
    return FunctionAccessEntry(
        provider_name=provider_name,
        function_title="fnc",
        permissions=permissions,
        business_model=Job.BUSINESS_MODEL_SUBSIDIZED,
    )


class TestCanRetrieveJob:
    def test_raises_for_none_provider(self):
        """Raises ValueError when provider is None."""
        user = User.objects.create_user(username="none")
        with pytest.raises(ValueError):
            ProviderAccessPolicy.can_retrieve_job(user, None, "fnc")

    @pytest.mark.parametrize(
        "permissions,expected",
        [
            ({PLATFORM_PERMISSION_JOB_READ}, True),
            (set(), False),
        ],
    )
    def test_grant(self, permissions, expected):
        """Access depends on whether accessible_functions includes JOB_READ for the provider."""
        user = User.objects.create_user(username="client")
        provider = Provider.objects.create(name="provider")
        functions = [_entry("provider", permissions)] if permissions else []
        accessible = FunctionAccessResult(has_response=True, functions=functions)
        assert ProviderAccessPolicy.can_retrieve_job(user, provider, "fnc", accessible) is expected

    class TestLegacyGroups:
        def test_true_admin_groups(self):
            """User belonging to a provider admin group can retrieve jobs."""
            user = User.objects.create_user(username="admin")
            provider = Provider.objects.create(name="provider")
            g = Group.objects.create(name="group")
            user.groups.add(g)
            provider.admin_groups.add(g)
            assert ProviderAccessPolicy.can_retrieve_job(user, provider, "fnc") is True

        def test_false_when_not_admin(self):
            """User with no groups cannot retrieve jobs from any provider."""
            user = User.objects.create_user(username="noadmin")
            provider = Provider.objects.create(name="provider2")
            assert ProviderAccessPolicy.can_retrieve_job(user, provider, "fnc") is False

        def test_false_when_wrong_groups(self):
            """User whose groups do not match the provider admin groups is denied."""
            user = User.objects.create_user(username="wronggroups")
            user.groups.add(Group.objects.create(name="user_group"))
            provider = Provider.objects.create(name="provider3")
            provider.admin_groups.add(Group.objects.create(name="admin_group"))
            assert ProviderAccessPolicy.can_retrieve_job(user, provider, "fnc") is False

        def test_falls_back_to_groups_when_no_response(self):
            """Falls back to legacy group check when the runtime instance returns no response."""
            user = User.objects.create_user(username="fallback")
            provider = Provider.objects.create(name="provider4")
            g = Group.objects.create(name="fallback_group")
            user.groups.add(g)
            provider.admin_groups.add(g)
            accessible = FunctionAccessResult(has_response=False)
            assert ProviderAccessPolicy.can_retrieve_job(user, provider, "fnc", accessible) is True


class TestCanReadLogs:
    @pytest.mark.parametrize(
        "permissions,expected",
        [
            ({PLATFORM_PERMISSION_PROVIDER_LOGS}, True),
            (set(), False),
        ],
    )
    def test_grant(self, permissions, expected):
        """Provider log access is granted if the entry includes PLATFORM_PERMISSION_PROVIDER_LOGS."""
        user = User.objects.create_user(username="client")
        provider = Provider.objects.create(name="provider")
        functions = [_entry("provider", permissions)] if permissions else []
        accessible = FunctionAccessResult(has_response=True, functions=functions)
        assert ProviderAccessPolicy.can_read_logs(user, provider, "fnc", accessible) is expected


class TestCanListJobs:
    @pytest.mark.parametrize(
        "permissions,expected",
        [
            ({PLATFORM_PERMISSION_PROVIDER_JOBS}, True),
            (set(), False),
        ],
    )
    def test_grant(self, permissions, expected):
        """Job list access is granted if the entry includes PLATFORM_PERMISSION_PROVIDER_JOBS."""
        user = User.objects.create_user(username="client")
        provider = Provider.objects.create(name="provider")
        functions = [_entry("provider", permissions)] if permissions else []
        accessible = FunctionAccessResult(has_response=True, functions=functions)
        assert ProviderAccessPolicy.can_list_jobs(user, provider, "fnc", accessible) is expected


class TestCanManageFiles:
    @pytest.mark.parametrize(
        "permissions,expected",
        [
            ({PLATFORM_PERMISSION_PROVIDER_FILES}, True),
            (set(), False),
        ],
    )
    def test_grant(self, permissions, expected):
        """File management access is granted if the entry includes PLATFORM_PERMISSION_PROVIDER_FILES."""
        user = User.objects.create_user(username="client")
        provider = Provider.objects.create(name="provider")
        functions = [_entry("provider", permissions)] if permissions else []
        accessible = FunctionAccessResult(has_response=True, functions=functions)
        assert ProviderAccessPolicy.can_manage_files(user, provider, "fnc", accessible) is expected


class TestCanUploadFunction:
    @pytest.mark.parametrize(
        "permissions,expected",
        [
            ({PLATFORM_PERMISSION_PROVIDER_UPLOAD}, True),
            (set(), False),
        ],
    )
    def test_grant(self, permissions, expected):
        """Function upload access is granted if the entry includes PLATFORM_PERMISSION_PROVIDER_UPLOAD."""
        user = User.objects.create_user(username="client")
        provider = Provider.objects.create(name="provider")
        functions = [_entry("provider", permissions)] if permissions else []
        accessible = FunctionAccessResult(has_response=True, functions=functions)
        assert ProviderAccessPolicy.can_upload_function(user, provider, "fnc", accessible) is expected
