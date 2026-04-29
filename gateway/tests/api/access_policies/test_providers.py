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
        user = User.objects.create_user(username="none")
        with pytest.raises(ValueError):
            ProviderAccessPolicy.can_retrieve_job(user, None, "fnc")

    def test_grant(self):
        user = User.objects.create_user(username="client")
        provider = Provider.objects.create(name="provider")

        accessible = FunctionAccessResult(has_response=True, functions=[])
        assert ProviderAccessPolicy.can_retrieve_job(user, provider, "fnc", accessible) is False

        entry = _entry("provider", {PLATFORM_PERMISSION_JOB_READ})
        accessible = FunctionAccessResult(has_response=True, functions=[entry])
        assert ProviderAccessPolicy.can_retrieve_job(user, provider, "fnc", accessible) is True

    class TestLegacyGroups:
        def test_true_admin_groups(self):
            user = User.objects.create_user(username="admin")
            provider = Provider.objects.create(name="provider")
            g = Group.objects.create(name="group")
            user.groups.add(g)
            provider.admin_groups.add(g)
            assert ProviderAccessPolicy.can_retrieve_job(user, provider, "fnc") is True

        def test_false_when_not_admin(self):
            user = User.objects.create_user(username="noadmin")
            provider = Provider.objects.create(name="provider2")
            assert ProviderAccessPolicy.can_retrieve_job(user, provider, "fnc") is False

        def test_false_when_wrong_groups(self):
            user = User.objects.create_user(username="wronggroups")
            user.groups.add(Group.objects.create(name="user_group"))
            provider = Provider.objects.create(name="provider3")
            provider.admin_groups.add(Group.objects.create(name="admin_group"))
            assert ProviderAccessPolicy.can_retrieve_job(user, provider, "fnc") is False

        def test_falls_back_to_groups_when_no_response(self):
            user = User.objects.create_user(username="fallback")
            provider = Provider.objects.create(name="provider4")
            g = Group.objects.create(name="fallback_group")
            user.groups.add(g)
            provider.admin_groups.add(g)
            accessible = FunctionAccessResult(has_response=False)
            assert ProviderAccessPolicy.can_retrieve_job(user, provider, "fnc", accessible) is True


class TestCanReadLogs:
    def test_grant(self):
        user = User.objects.create_user(username="client")
        provider = Provider.objects.create(name="provider")

        accessible = FunctionAccessResult(has_response=True, functions=[])
        assert ProviderAccessPolicy.can_read_logs(user, provider, "fnc", accessible) is False

        entry = _entry("provider", {PLATFORM_PERMISSION_PROVIDER_LOGS})
        accessible = FunctionAccessResult(has_response=True, functions=[entry])
        assert ProviderAccessPolicy.can_read_logs(user, provider, "fnc", accessible) is True


class TestCanListJobs:
    def test_grant(self):
        user = User.objects.create_user(username="client")
        provider = Provider.objects.create(name="provider")

        accessible = FunctionAccessResult(has_response=True, functions=[])
        assert ProviderAccessPolicy.can_list_jobs(user, provider, "fnc", accessible) is False

        entry = _entry("provider", {PLATFORM_PERMISSION_PROVIDER_JOBS})
        accessible = FunctionAccessResult(has_response=True, functions=[entry])
        assert ProviderAccessPolicy.can_list_jobs(user, provider, "fnc", accessible) is True


class TestCanManageFiles:
    def test_grant(self):
        user = User.objects.create_user(username="client")
        provider = Provider.objects.create(name="provider")

        accessible = FunctionAccessResult(has_response=True, functions=[])
        assert ProviderAccessPolicy.can_manage_files(user, provider, "fnc", accessible) is False

        entry = _entry("provider", {PLATFORM_PERMISSION_PROVIDER_FILES})
        accessible = FunctionAccessResult(has_response=True, functions=[entry])
        assert ProviderAccessPolicy.can_manage_files(user, provider, "fnc", accessible) is True


class TestCanUploadFunction:
    def test_grant(self):
        user = User.objects.create_user(username="client")
        provider = Provider.objects.create(name="provider")

        accessible = FunctionAccessResult(has_response=True, functions=[])
        assert ProviderAccessPolicy.can_upload_function(user, provider, "fnc", accessible) is False

        entry = _entry("provider", {PLATFORM_PERMISSION_PROVIDER_UPLOAD})
        accessible = FunctionAccessResult(has_response=True, functions=[entry])
        assert ProviderAccessPolicy.can_upload_function(user, provider, "fnc", accessible) is True
