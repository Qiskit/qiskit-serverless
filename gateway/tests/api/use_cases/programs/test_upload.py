"""Unit tests for UploadFunctionUseCase."""

import pytest
from django.contrib.auth.models import User
from rest_framework.exceptions import ValidationError as DRFValidationError

from api.domain.exceptions.function_configuration_exception import FunctionConfigurationException
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.use_cases.programs.upload import UploadFunctionUseCase
from api.use_cases.programs.upload_input import UploadFunctionInput
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import ComputeProfile, Program, Provider
from tests.utils import TestUtils

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return User.objects.create_user(username="author")


@pytest.fixture
def ce_project(settings):
    """Active default CodeEngineProject so a Fleets create() does not need one passed in."""
    settings.CE_DEFAULT_PROJECT_NAME = "default-ce-project"
    return TestUtils.get_or_create_ce_project(
        project_name="default-ce-project",
        project_id="ce-proj-id",
    )


class TestUploadFunctionUseCase:
    def test_creates_new_private_function(self, user):
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        result = UploadFunctionUseCase().execute(
            user, accessible, UploadFunctionInput(title="my-fn", entrypoint="main.py")
        )

        assert result.title == "my-fn"
        assert result.author == user

    def test_updates_existing_private_function(self, user):
        existing = Program.objects.create(title="my-fn", author=user, entrypoint="old.py")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        result = UploadFunctionUseCase().execute(
            user, accessible, UploadFunctionInput(title="my-fn", entrypoint="main.py")
        )

        assert result.pk == existing.pk
        assert result.title == "my-fn"

    def test_raises_not_found_when_no_permission_for_custom_function(self, user):
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        with pytest.raises(FunctionNotFoundException):
            UploadFunctionUseCase().execute(user, accessible, UploadFunctionInput(title="my-fn", entrypoint="main.py"))

    def test_creates_provider_function(self, user):
        group = TestUtils.get_or_create_group("my-provider")
        TestUtils.add_user_to_group(user, group)
        provider = Provider.objects.create(name="my-provider")
        provider.admin_groups.add(group)
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        result = UploadFunctionUseCase().execute(
            user, accessible, UploadFunctionInput(title="my-fn", provider="my-provider", entrypoint="main.py")
        )

        assert result.title == "my-fn"
        assert result.provider is not None
        assert result.provider.name == "my-provider"

    def test_updates_existing_provider_function(self, user):
        group = TestUtils.get_or_create_group("my-provider")
        TestUtils.add_user_to_group(user, group)
        provider = Provider.objects.create(name="my-provider")
        provider.admin_groups.add(group)
        existing = Program.objects.create(title="my-fn", provider=provider, author=user, entrypoint="old.py")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        result = UploadFunctionUseCase().execute(
            user, accessible, UploadFunctionInput(title="my-fn", provider="my-provider", entrypoint="new.py")
        )

        assert result.pk == existing.pk
        assert result.entrypoint == "new.py"

    def test_reupload_by_different_provider_admin_preserves_original_author(self, user):
        group = TestUtils.get_or_create_group("my-provider")
        TestUtils.add_user_to_group(user, group)
        other_admin = User.objects.create_user(username="other-admin")
        TestUtils.add_user_to_group(other_admin, group)
        provider = Provider.objects.create(name="my-provider")
        provider.admin_groups.add(group)
        existing = Program.objects.create(title="my-fn", provider=provider, author=user, entrypoint="old.py")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        result = UploadFunctionUseCase().execute(
            other_admin, accessible, UploadFunctionInput(title="my-fn", provider="my-provider", entrypoint="new.py")
        )

        assert result.pk == existing.pk
        assert result.author == user

    def test_reupload_switching_to_fleets_without_ce_project_raises(self, user, settings):
        settings.CE_DEFAULT_PROJECT_NAME = "nonexistent-project"
        existing = Program.objects.create(title="my-fn", author=user, entrypoint="old.py", runner=Program.RAY)
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        with pytest.raises(FunctionConfigurationException):
            UploadFunctionUseCase().execute(
                user,
                accessible,
                UploadFunctionInput(title="my-fn", entrypoint="old.py", runner=Program.FLEETS),
            )

        existing.refresh_from_db()
        assert existing.runner == Program.RAY

    def test_reupload_without_changing_runner_ignores_missing_ce_project(self, user, settings):
        settings.CE_DEFAULT_PROJECT_NAME = "nonexistent-project"
        Program.objects.create(title="my-fn", author=user, entrypoint="old.py", runner=Program.FLEETS)
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        result = UploadFunctionUseCase().execute(
            user,
            accessible,
            UploadFunctionInput(title="my-fn", entrypoint="new.py"),
        )

        assert result.entrypoint == "new.py"
        assert result.runner == Program.FLEETS

    def test_author_can_update_provider_function_without_admin_group(self, user):
        provider = Provider.objects.create(name="my-provider")
        Program.objects.create(title="my-fn", provider=provider, author=user, entrypoint="old.py")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        result = UploadFunctionUseCase().execute(
            user, accessible, UploadFunctionInput(title="my-fn", provider="my-provider", entrypoint="new.py")
        )

        assert result.entrypoint == "new.py"

    def test_non_author_non_admin_cannot_update_provider_function(self, user):
        other = User.objects.create_user(username="other")
        provider = Provider.objects.create(name="my-provider")
        Program.objects.create(title="my-fn", provider=provider, author=user, entrypoint="old.py")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        with pytest.raises(FunctionNotFoundException):
            UploadFunctionUseCase().execute(
                other, accessible, UploadFunctionInput(title="my-fn", provider="my-provider", entrypoint="new.py")
            )

    def test_creating_new_provider_function_requires_admin_group(self, user):
        Provider.objects.create(name="my-provider")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        with pytest.raises(FunctionNotFoundException):
            UploadFunctionUseCase().execute(
                user, accessible, UploadFunctionInput(title="new-fn", provider="my-provider", entrypoint="main.py")
            )

    def test_raises_not_found_when_provider_not_found(self, user):
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        with pytest.raises(FunctionNotFoundException):
            UploadFunctionUseCase().execute(
                user,
                accessible,
                UploadFunctionInput(title="my-fn", provider="nonexistent-provider", entrypoint="main.py"),
            )

    def test_update_encrypts_env_vars(self, user):
        import json

        Program.objects.create(title="my-fn", author=user, entrypoint="main.py")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        result = UploadFunctionUseCase().execute(
            user,
            accessible,
            UploadFunctionInput(title="my-fn", entrypoint="main.py", env_vars='{"my_token": "plaintext-secret"}'),
        )

        stored = json.loads(result.env_vars) if isinstance(result.env_vars, str) else result.env_vars
        assert stored["my_token"] != "plaintext-secret"

    def test_create_with_sizes_but_no_default_size_is_rejected(self, user):
        """A new function has no stored catalog to fall back on, so 'default_size' is mandatory with 'sizes'."""
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        with pytest.raises(DRFValidationError):
            UploadFunctionUseCase().execute(
                user,
                accessible,
                UploadFunctionInput(title="my-fn", entrypoint="main.py", sizes={"m": "16x128"}),
            )

        assert not Program.objects.filter(title="my-fn").exists()

    def test_create_with_default_size_but_no_sizes_is_rejected(self, user):
        """'default_size' alone at creation would point at a catalog that does not exist yet."""
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        with pytest.raises(DRFValidationError):
            UploadFunctionUseCase().execute(
                user,
                accessible,
                UploadFunctionInput(title="my-fn", entrypoint="main.py", default_size="m"),
            )

        assert not Program.objects.filter(title="my-fn").exists()

    def test_create_with_default_size_not_in_sizes_is_rejected(self, user):
        """A 'default_size' that does not name one of the sizes just declared is rejected."""
        ComputeProfile.objects.create(compute_profile_id="16x128")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        with pytest.raises(DRFValidationError):
            UploadFunctionUseCase().execute(
                user,
                accessible,
                UploadFunctionInput(title="my-fn", entrypoint="main.py", sizes={"m": "16x128"}, default_size="l"),
            )

        assert not Program.objects.filter(title="my-fn").exists()

    def test_create_with_sizes_and_matching_default_size_succeeds(self, user, ce_project):
        """Sending both together, with 'default_size' among 'sizes', creates the catalog and the default."""
        ComputeProfile.objects.create(compute_profile_id="16x128")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        result = UploadFunctionUseCase().execute(
            user,
            accessible,
            UploadFunctionInput(
                title="my-fn", entrypoint="main.py", runner=Program.FLEETS, sizes={"m": "16x128"}, default_size="m"
            ),
        )

        assert result.function_sizes.count() == 1
        assert result.default_size is not None
        assert result.default_size.function_size == "m"

    def test_create_ray_function_without_sizes_does_not_seed_function_size(self, user):
        """Sizing is a Fleets concept; a Ray function created without 'sizes' gets none seeded."""
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        result = UploadFunctionUseCase().execute(
            user, accessible, UploadFunctionInput(title="my-fn", entrypoint="main.py")
        )

        assert result.runner == Program.RAY
        assert result.function_sizes.count() == 0
        assert result.default_size is None

    def test_create_ray_function_with_valid_sizes_validates_but_does_not_persist(self, user):
        """A self-consistent 'sizes'/'default_size' pair for Ray validates fine but is never written."""
        ComputeProfile.objects.create(compute_profile_id="16x128")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        result = UploadFunctionUseCase().execute(
            user,
            accessible,
            UploadFunctionInput(title="my-fn", entrypoint="main.py", sizes={"m": "16x128"}, default_size="m"),
        )

        assert result.runner == Program.RAY
        assert result.function_sizes.count() == 0
        assert result.default_size is None

    def test_create_ray_function_with_invalid_sizes_still_rejected(self, user):
        """Validation runs the same regardless of runner: a mismatched 'default_size' is still a 400 for Ray."""
        ComputeProfile.objects.create(compute_profile_id="16x128")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        with pytest.raises(DRFValidationError):
            UploadFunctionUseCase().execute(
                user,
                accessible,
                UploadFunctionInput(title="my-fn", entrypoint="main.py", sizes={"m": "16x128"}, default_size="l"),
            )

        assert not Program.objects.filter(title="my-fn").exists()

    def test_update_ray_function_with_valid_sizes_validates_but_does_not_persist(self, user):
        """Same as create: a valid 'sizes'/'default_size' pair sent to an existing Ray function is not persisted."""
        Program.objects.create(title="my-fn", author=user, entrypoint="old.py")
        ComputeProfile.objects.create(compute_profile_id="16x128")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        result = UploadFunctionUseCase().execute(
            user,
            accessible,
            UploadFunctionInput(title="my-fn", entrypoint="new.py", sizes={"m": "16x128"}, default_size="m"),
        )

        assert result.function_sizes.count() == 0
        assert result.default_size is None

    def test_create_fleets_function_without_sizes_seeds_default_from_settings(self, user, ce_project, settings):
        """No sizes declared: a Fleets function still gets a size, seeded from the deployment default."""
        settings.DEFAULT_FUNCTION_SIZE_PROFILE = "16x128"
        settings.DEFAULT_FUNCTION_SIZE = "m"
        ComputeProfile.objects.create(compute_profile_id="16x128")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        result = UploadFunctionUseCase().execute(
            user,
            accessible,
            UploadFunctionInput(title="my-fn", entrypoint="main.py", runner=Program.FLEETS),
        )

        sizes = list(result.function_sizes.all())
        assert len(sizes) == 1
        assert sizes[0].function_size == "m"
        assert sizes[0].compute_profile.compute_profile_id == "16x128"
        assert result.default_size == sizes[0]

    def test_create_fleets_function_without_sizes_skips_seed_when_profile_unregistered(
        self, user, ce_project, settings
    ):
        """No sizes declared and the seed profile is missing: created sizeless rather than failing."""
        settings.DEFAULT_FUNCTION_SIZE_PROFILE = "unregistered-profile"
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        result = UploadFunctionUseCase().execute(
            user,
            accessible,
            UploadFunctionInput(title="my-fn", entrypoint="main.py", runner=Program.FLEETS),
        )

        assert result.function_sizes.count() == 0
        assert result.default_size is None
