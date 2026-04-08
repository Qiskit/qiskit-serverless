"""
This file contains e2e tests for Mock Token authentication process
in local environments.
"""

from unittest.mock import MagicMock

import pytest
from rest_framework import exceptions

from api.authentication import MockTokenBackend
from core.models import RUN_PROGRAM_PERMISSION, VIEW_PROGRAM_PERMISSION
from api.repositories.providers import ProviderRepository

# This allows to access to the db and create/rollback the transaction per test, like the classic Django unittests do
pytestmark = pytest.mark.django_db


def test_default_authentication_workflow(settings):
    """This test verifies the authentication process for Mock Token."""
    backend = MockTokenBackend()
    request = MagicMock()
    request.META = {"HTTP_AUTHORIZATION": "Bearer my_awesome_token"}

    provider_repository = ProviderRepository()

    settings.SETTINGS_AUTH_MOCK_TOKEN = "my_awesome_token"
    user, token = backend.authenticate(request)
    assert user.username == "mockuser"
    assert token.token.decode() == "my_awesome_token"

    for group in user.groups.all():
        permissions = list(group.permissions.values_list("codename", flat=True))
        assert permissions == [RUN_PROGRAM_PERMISSION, VIEW_PROGRAM_PERMISSION]

    provider = provider_repository.get_provider_by_name("mockprovider")
    assert provider is not None

    provider_groups = list(provider.admin_groups.values_list("name", flat=True))
    assert provider_groups == ["mockgroup"]

    groups = user.groups.all()
    metadata = getattr(groups[0], "metadata", None)
    assert metadata is None


def test_incorrect_authorization_header(settings):
    """This test verifies that user is None if the authentication fails."""
    backend = MockTokenBackend()
    request = MagicMock()
    request.META = {"HTTP_AUTHORIZATION": "Bearer my_awesome_token"}

    settings.SETTINGS_AUTH_MOCK_TOKEN = "other_awesome_token"
    with pytest.raises(exceptions.AuthenticationFailed):
        backend.authenticate(request)
