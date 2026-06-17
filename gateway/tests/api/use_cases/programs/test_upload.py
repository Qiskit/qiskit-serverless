"""Unit tests for UploadFunctionUseCase."""

import pytest
from django.contrib.auth.models import User

from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.use_cases.programs.upload import UploadFunctionUseCase
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Program, Provider
from tests.utils import TestUtils

pytestmark = pytest.mark.django_db

VALID_DATA = {"title": "my-fn", "entrypoint": "main.py"}


@pytest.fixture
def user():
    return User.objects.create_user(username="author")


class TestUploadFunctionUseCase:
    def test_creates_new_private_function(self, user):
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        result = UploadFunctionUseCase().execute(user, accessible, VALID_DATA)

        assert result.title == "my-fn"
        assert result.author == user

    def test_updates_existing_private_function(self, user):
        existing = Program.objects.create(title="my-fn", author=user, entrypoint="old.py")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        result = UploadFunctionUseCase().execute(user, accessible, VALID_DATA)

        assert result.pk == existing.pk
        assert result.title == "my-fn"

    def test_raises_not_found_when_no_permission_for_custom_function(self, user):
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        with pytest.raises(FunctionNotFoundException):
            UploadFunctionUseCase().execute(user, accessible, VALID_DATA)

    def test_creates_provider_function(self, user):
        group = TestUtils.get_or_create_group("my-provider")
        TestUtils.add_user_to_group(user, group)
        provider = Provider.objects.create(name="my-provider")
        provider.admin_groups.add(group)
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        result = UploadFunctionUseCase().execute(
            user, accessible, {"title": "my-provider/my-fn", "entrypoint": "main.py"}
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
            user, accessible, {"title": "my-provider/my-fn", "entrypoint": "new.py"}
        )

        assert result.pk == existing.pk
        assert result.entrypoint == "new.py"

    def test_raises_not_found_when_provider_not_found(self, user):
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        with pytest.raises(FunctionNotFoundException):
            UploadFunctionUseCase().execute(
                user, accessible, {"title": "nonexistent-provider/my-fn", "entrypoint": "main.py"}
            )
