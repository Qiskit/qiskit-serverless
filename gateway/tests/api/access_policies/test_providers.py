"""Tests for access policies."""

import pytest

from django.contrib.auth.models import Group, User

from api.access_policies.providers import ProviderAccessPolicy
from core.domain.authorization.function_access_entry import FunctionAccessEntry
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import (
    Job,
    PLATFORM_PERMISSION_JOB_RETRIEVE,
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
        function_title="some-fn",
        permissions=permissions,
        business_model=Job.BUSINESS_MODEL_SUBSIDIZED,
    )


# ---------------------------------------------------------------------------
# can_retrieve_job
# ---------------------------------------------------------------------------


def test_can_retrieve_job_raises_for_none_provider():
    user = User.objects.create_user(username="rj_none")
    with pytest.raises(ValueError):
        ProviderAccessPolicy.can_retrieve_job(user, None)


def test_can_retrieve_job_true_via_admin_groups():
    user = User.objects.create_user(username="rj_admin")
    provider = Provider.objects.create(name="rj-provider")
    g = Group.objects.create(name="rj_group")
    user.groups.add(g)
    provider.admin_groups.add(g)
    assert ProviderAccessPolicy.can_retrieve_job(user, provider) is True


def test_can_retrieve_job_false_when_not_admin():
    user = User.objects.create_user(username="rj_noadmin")
    provider = Provider.objects.create(name="rj-provider2")
    assert ProviderAccessPolicy.can_retrieve_job(user, provider) is False


def test_can_retrieve_job_false_when_wrong_groups():
    user = User.objects.create_user(username="rj_wronggroups")
    user.groups.add(Group.objects.create(name="rj_user_group"))
    provider = Provider.objects.create(name="rj-provider3")
    provider.admin_groups.add(Group.objects.create(name="rj_admin_group"))
    assert ProviderAccessPolicy.can_retrieve_job(user, provider) is False


def test_can_retrieve_job_true_via_client():
    user = User.objects.create_user(username="rj_client")
    provider = Provider.objects.create(name="rj-provider4")
    entry = _entry("rj-provider4", {PLATFORM_PERMISSION_JOB_RETRIEVE})
    accessible = FunctionAccessResult(has_response=True, functions=[entry])
    assert ProviderAccessPolicy.can_retrieve_job(user, provider, accessible) is True


def test_can_retrieve_job_false_via_client_wrong_permission():
    user = User.objects.create_user(username="rj_client2")
    provider = Provider.objects.create(name="rj-provider5")
    entry = _entry("rj-provider5", {PLATFORM_PERMISSION_PROVIDER_LOGS})
    accessible = FunctionAccessResult(has_response=True, functions=[entry])
    assert ProviderAccessPolicy.can_retrieve_job(user, provider, accessible) is False


def test_can_retrieve_job_false_via_client_no_entries():
    user = User.objects.create_user(username="rj_client3")
    provider = Provider.objects.create(name="rj-provider6")
    accessible = FunctionAccessResult(has_response=True, functions=[])
    assert ProviderAccessPolicy.can_retrieve_job(user, provider, accessible) is False


def test_can_retrieve_job_falls_back_to_groups_when_no_response():
    user = User.objects.create_user(username="rj_fallback")
    provider = Provider.objects.create(name="rj-provider7")
    g = Group.objects.create(name="rj_fallback_group")
    user.groups.add(g)
    provider.admin_groups.add(g)
    accessible = FunctionAccessResult(has_response=False)
    assert ProviderAccessPolicy.can_retrieve_job(user, provider, accessible) is True


# ---------------------------------------------------------------------------
# can_read_logs
# ---------------------------------------------------------------------------


def test_can_read_logs_true_via_client():
    user = User.objects.create_user(username="rl_client")
    provider = Provider.objects.create(name="rl-provider")
    entry = _entry("rl-provider", {PLATFORM_PERMISSION_PROVIDER_LOGS})
    accessible = FunctionAccessResult(has_response=True, functions=[entry])
    assert ProviderAccessPolicy.can_read_logs(user, provider, accessible) is True


def test_can_read_logs_false_via_client_wrong_permission():
    user = User.objects.create_user(username="rl_client2")
    provider = Provider.objects.create(name="rl-provider2")
    entry = _entry("rl-provider2", {PLATFORM_PERMISSION_JOB_RETRIEVE})
    accessible = FunctionAccessResult(has_response=True, functions=[entry])
    assert ProviderAccessPolicy.can_read_logs(user, provider, accessible) is False


# ---------------------------------------------------------------------------
# can_list_jobs
# ---------------------------------------------------------------------------


def test_can_list_jobs_true_via_client():
    user = User.objects.create_user(username="lj_client")
    provider = Provider.objects.create(name="lj-provider")
    entry = _entry("lj-provider", {PLATFORM_PERMISSION_PROVIDER_JOBS})
    accessible = FunctionAccessResult(has_response=True, functions=[entry])
    assert ProviderAccessPolicy.can_list_jobs(user, provider, accessible) is True


def test_can_list_jobs_false_via_client_wrong_permission():
    user = User.objects.create_user(username="lj_client2")
    provider = Provider.objects.create(name="lj-provider2")
    entry = _entry("lj-provider2", {PLATFORM_PERMISSION_JOB_RETRIEVE})
    accessible = FunctionAccessResult(has_response=True, functions=[entry])
    assert ProviderAccessPolicy.can_list_jobs(user, provider, accessible) is False


# ---------------------------------------------------------------------------
# can_manage_files
# ---------------------------------------------------------------------------


def test_can_manage_files_true_via_client():
    user = User.objects.create_user(username="mf_client")
    provider = Provider.objects.create(name="mf-provider")
    entry = _entry("mf-provider", {PLATFORM_PERMISSION_PROVIDER_FILES})
    accessible = FunctionAccessResult(has_response=True, functions=[entry])
    assert ProviderAccessPolicy.can_manage_files(user, provider, accessible) is True


def test_can_manage_files_false_via_client_wrong_permission():
    user = User.objects.create_user(username="mf_client2")
    provider = Provider.objects.create(name="mf-provider2")
    entry = _entry("mf-provider2", {PLATFORM_PERMISSION_PROVIDER_JOBS})
    accessible = FunctionAccessResult(has_response=True, functions=[entry])
    assert ProviderAccessPolicy.can_manage_files(user, provider, accessible) is False


# ---------------------------------------------------------------------------
# can_upload_function
# ---------------------------------------------------------------------------


def test_can_upload_function_true_via_client():
    user = User.objects.create_user(username="uf_client")
    provider = Provider.objects.create(name="uf-provider")
    entry = _entry("uf-provider", {PLATFORM_PERMISSION_PROVIDER_UPLOAD})
    accessible = FunctionAccessResult(has_response=True, functions=[entry])
    assert ProviderAccessPolicy.can_upload_function(user, provider, accessible) is True


def test_can_upload_function_false_via_client_wrong_permission():
    user = User.objects.create_user(username="uf_client2")
    provider = Provider.objects.create(name="uf-provider2")
    entry = _entry("uf-provider2", {PLATFORM_PERMISSION_PROVIDER_JOBS})
    accessible = FunctionAccessResult(has_response=True, functions=[entry])
    assert ProviderAccessPolicy.can_upload_function(user, provider, accessible) is False


# ---------------------------------------------------------------------------
# Function-level granularity: permission for fn-A does NOT grant access to fn-B
# ---------------------------------------------------------------------------


def _entry_named(provider_name, function_title, permissions):
    return FunctionAccessEntry(
        provider_name=provider_name,
        function_title=function_title,
        permissions=permissions,
        business_model=Job.BUSINESS_MODEL_SUBSIDIZED,
    )


def test_can_retrieve_job_true_for_exact_function():
    """Permission on fn-A grants access when function_title=fn-A."""
    user = User.objects.create_user(username="fg_rj1")
    provider = Provider.objects.create(name="fg-provider")
    entry = _entry_named("fg-provider", "sampler", {PLATFORM_PERMISSION_JOB_RETRIEVE})
    accessible = FunctionAccessResult(has_response=True, functions=[entry])
    assert ProviderAccessPolicy.can_retrieve_job(user, provider, accessible, function_title="sampler") is True


def test_can_retrieve_job_false_for_different_function():
    """Permission on fn-A does NOT grant access when function_title=fn-B."""
    user = User.objects.create_user(username="fg_rj2")
    provider = Provider.objects.create(name="fg-provider2")
    entry = _entry_named("fg-provider2", "sampler", {PLATFORM_PERMISSION_JOB_RETRIEVE})
    accessible = FunctionAccessResult(has_response=True, functions=[entry])
    assert ProviderAccessPolicy.can_retrieve_job(user, provider, accessible, function_title="estimator") is False


def test_can_read_logs_false_for_different_function():
    user = User.objects.create_user(username="fg_rl1")
    provider = Provider.objects.create(name="fg-provider3")
    entry = _entry_named("fg-provider3", "sampler", {PLATFORM_PERMISSION_PROVIDER_LOGS})
    accessible = FunctionAccessResult(has_response=True, functions=[entry])
    assert ProviderAccessPolicy.can_read_logs(user, provider, accessible, function_title="estimator") is False


def test_can_list_jobs_false_for_different_function():
    user = User.objects.create_user(username="fg_lj1")
    provider = Provider.objects.create(name="fg-provider4")
    entry = _entry_named("fg-provider4", "sampler", {PLATFORM_PERMISSION_PROVIDER_JOBS})
    accessible = FunctionAccessResult(has_response=True, functions=[entry])
    assert ProviderAccessPolicy.can_list_jobs(user, provider, accessible, function_title="estimator") is False


def test_can_manage_files_false_for_different_function():
    user = User.objects.create_user(username="fg_mf1")
    provider = Provider.objects.create(name="fg-provider5")
    entry = _entry_named("fg-provider5", "sampler", {PLATFORM_PERMISSION_PROVIDER_FILES})
    accessible = FunctionAccessResult(has_response=True, functions=[entry])
    assert ProviderAccessPolicy.can_manage_files(user, provider, accessible, function_title="estimator") is False


def test_can_upload_function_false_for_different_function():
    user = User.objects.create_user(username="fg_uf1")
    provider = Provider.objects.create(name="fg-provider6")
    entry = _entry_named("fg-provider6", "sampler", {PLATFORM_PERMISSION_PROVIDER_UPLOAD})
    accessible = FunctionAccessResult(has_response=True, functions=[entry])
    assert ProviderAccessPolicy.can_upload_function(user, provider, accessible, function_title="estimator") is False


def test_no_function_title_falls_back_to_provider_level():
    """Without function_title, check remains at provider level (any function with permission grants access)."""
    user = User.objects.create_user(username="fg_pl1")
    provider = Provider.objects.create(name="fg-provider7")
    entry = _entry_named("fg-provider7", "sampler", {PLATFORM_PERMISSION_JOB_RETRIEVE})
    accessible = FunctionAccessResult(has_response=True, functions=[entry])
    # No function_title → provider-level → True because sampler has the permission
    assert ProviderAccessPolicy.can_retrieve_job(user, provider, accessible) is True
