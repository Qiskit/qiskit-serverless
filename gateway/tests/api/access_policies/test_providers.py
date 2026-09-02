"""Tests for access policies."""

import pytest

from django.contrib.auth.models import Group, User

from api.access_policies.providers import ProviderAccessPolicy
from core.domain.authorization.function_access_entry import FunctionAccessEntry
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.domain.business_models import BusinessModel
from core.models import (
    Job,
    PLATFORM_PERMISSION_PROVIDER_FILES_READ,
    PLATFORM_PERMISSION_PROVIDER_FILES_WRITE,
    PLATFORM_PERMISSION_JOBS_READ,
    PLATFORM_PERMISSION_PROVIDER_LOGS,
    PLATFORM_PERMISSION_WRITE,
    Program,
    Provider,
)

pytestmark = pytest.mark.django_db


def _entry(provider_name, permissions):
    return FunctionAccessEntry(
        provider_name=provider_name,
        function_title="fnc",
        permissions=permissions,
        business_model=BusinessModel.LICENSED,
    )


# Both auth paths, plus the no-response fallback. The owner is allowed on all three.
AUTH_PATHS = [
    None,
    FunctionAccessResult(use_legacy_authorization=True),
    FunctionAccessResult(use_legacy_authorization=False, functions=[]),
]


class TestCanRetrieveJob:
    def test_raises_for_none_provider(self):
        """Raises ValueError when provider is None."""
        user = User.objects.create_user(username="none")
        with pytest.raises(ValueError):
            ProviderAccessPolicy.can_retrieve_job(user, None, "fnc")

    @pytest.mark.parametrize(
        "permissions,expected",
        [
            ({PLATFORM_PERMISSION_JOBS_READ}, True),
            (set(), False),
        ],
    )
    def test_grant(self, permissions, expected):
        """Access depends on whether accessible_functions includes PROVIDER_JOBS for the provider."""
        user = User.objects.create_user(username="client")
        provider = Provider.objects.create(name="provider")
        functions = [_entry("provider", permissions)] if permissions else []
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=functions)
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
            accessible = FunctionAccessResult(use_legacy_authorization=True)
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
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=functions)
        assert ProviderAccessPolicy.can_read_logs(user, provider, "fnc", accessible) is expected


class TestCanListJobs:
    @pytest.mark.parametrize(
        "permissions,expected",
        [
            ({PLATFORM_PERMISSION_JOBS_READ}, True),
            (set(), False),
        ],
    )
    def test_grant(self, permissions, expected):
        """Job list access is granted if the entry includes PLATFORM_PERMISSION_JOBS_READ."""
        user = User.objects.create_user(username="client")
        provider = Provider.objects.create(name="provider")
        functions = [_entry("provider", permissions)] if permissions else []
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=functions)
        assert ProviderAccessPolicy.can_list_jobs(user, provider, "fnc", accessible) is expected


class TestCanReadFiles:
    @pytest.mark.parametrize(
        "permissions,expected",
        [
            ({PLATFORM_PERMISSION_PROVIDER_FILES_READ}, True),
            (set(), False),
        ],
    )
    def test_grant(self, permissions, expected):
        """File read access is granted if the entry includes PLATFORM_PERMISSION_PROVIDER_FILES_READ."""
        user = User.objects.create_user(username="client")
        provider = Provider.objects.create(name="provider")
        functions = [_entry("provider", permissions)] if permissions else []
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=functions)
        assert ProviderAccessPolicy.can_read_files(user, provider, "fnc", accessible) is expected


class TestCanWriteFiles:
    @pytest.mark.parametrize(
        "permissions,expected",
        [
            ({PLATFORM_PERMISSION_PROVIDER_FILES_WRITE}, True),
            (set(), False),
        ],
    )
    def test_grant(self, permissions, expected):
        """File write access is granted if the entry includes PLATFORM_PERMISSION_PROVIDER_FILES_WRITE."""
        user = User.objects.create_user(username="client")
        provider = Provider.objects.create(name="provider")
        functions = [_entry("provider", permissions)] if permissions else []
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=functions)
        assert ProviderAccessPolicy.can_write_files(user, provider, "fnc", accessible) is expected


class TestCanUploadFunction:
    @pytest.mark.parametrize(
        "permissions,expected",
        [
            ({PLATFORM_PERMISSION_WRITE}, True),
            (set(), False),
        ],
    )
    def test_grant(self, permissions, expected):
        """Function upload access is granted if the entry includes PLATFORM_PERMISSION_WRITE."""
        user = User.objects.create_user(username="client")
        provider = Provider.objects.create(name="provider")
        functions = [_entry("provider", permissions)] if permissions else []
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=functions)
        assert ProviderAccessPolicy.can_upload_function(user, provider, "fnc", accessible) is expected


class TestOwnership:
    """The owner of a function is an admin of it: authorship grants the provider operations.

    Ownership lives entirely in the shared `_check`, and each `can_*` wrapper is already proven to
    delegate to it by its own test class above -- so one representative operation covers all six.
    See specs/INSTANCES_AUTH.md "Design decisions" for why ownership alone suffices here while
    catalog visibility and run stay gated by the permission list.
    """

    @pytest.mark.parametrize("accessible", AUTH_PATHS)
    def test_owner_is_allowed_on_every_auth_path(self, accessible):
        """The author passes with no admin group and no entitlements."""
        user = User.objects.create_user(username="owner")
        provider = Provider.objects.create(name="provider")
        Program.objects.create(title="fnc", provider=provider, author=user)

        assert ProviderAccessPolicy.can_upload_function(user, provider, "fnc", accessible) is True

    @pytest.mark.parametrize("accessible", AUTH_PATHS)
    def test_non_owner_non_admin_still_denied(self, accessible):
        """Someone else's function is still denied: ownership is the only thing that was added."""
        owner = User.objects.create_user(username="owner")
        other = User.objects.create_user(username="other")
        provider = Provider.objects.create(name="provider")
        Program.objects.create(title="fnc", provider=provider, author=owner)

        assert ProviderAccessPolicy.can_upload_function(other, provider, "fnc", accessible) is False

    def test_nonexistent_function_falls_through_to_permission_branch(self):
        """A function that does not exist yet has no author, so creation still needs permission.

        This is what keeps AC3 ("creating a brand-new provider function still requires
        admin/write permissions") true without any dedicated code.
        """
        user = User.objects.create_user(username="creator")
        provider = Provider.objects.create(name="provider")
        # No Program row at all -- .exists() is False, so _check falls back to the group branch.
        accessible = FunctionAccessResult(use_legacy_authorization=True)

        assert ProviderAccessPolicy.can_upload_function(user, provider, "brand-new-fn", accessible) is False

    def test_ownership_does_not_cross_providers(self):
        """Owning providerA/my-fn must not grant provider operations on providerB/my-fn.

        Function titles are unique per provider, not globally. A check written as
        filter(title=..., author=user) without the provider clause would leak across
        providers -- including provider file writes and provider log reads.
        """
        user = User.objects.create_user(username="owner")
        provider_a = Provider.objects.create(name="provider-a")
        provider_b = Provider.objects.create(name="provider-b")
        Program.objects.create(title="my-fn", provider=provider_a, author=user)

        assert ProviderAccessPolicy.can_write_files(user, provider_a, "my-fn", None) is True
        assert ProviderAccessPolicy.can_write_files(user, provider_b, "my-fn", None) is False

    def test_is_provider_admin_unaffected_by_ownership(self):
        """is_provider_admin answers "admin of the whole provider" and must ignore authorship.

        It grants provider-wide job scope at api/use_cases/jobs/provider_list.py, so owning one
        function must not widen the caller's scope to every function of that provider.
        """
        user = User.objects.create_user(username="owner")
        provider = Provider.objects.create(name="provider")
        Program.objects.create(title="fnc", provider=provider, author=user)

        assert ProviderAccessPolicy.is_provider_admin(user, provider) is False
