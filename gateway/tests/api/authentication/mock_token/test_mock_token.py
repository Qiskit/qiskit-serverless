"""
This file contains e2e tests for Mock Token authentication process
in local environments.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from rest_framework import exceptions

from api.authentication import MockTokenBackend
from api.domain.authentication.authentication_group import AuthenticationGroup
from api.services.authentication.local_authentication import LocalAuthenticationService
from core.models import RUN_PROGRAM_PERMISSION, VIEW_PROGRAM_PERMISSION, Provider

# This allows to access to the db and create/rollback the transaction per test, like the classic Django unittests do
pytestmark = pytest.mark.django_db


def test_default_authentication_workflow(settings):
    """This test verifies the authentication process for Mock Token."""
    backend = MockTokenBackend()
    request = MagicMock()
    request.META = {"HTTP_AUTHORIZATION": "Bearer my_awesome_token"}

    settings.SETTINGS_AUTH_MOCK_TOKEN = "my_awesome_token"
    user, token = backend.authenticate(request)
    assert user.username == "mockuser"
    assert token.token.decode() == "my_awesome_token"

    for group in user.groups.all():
        permissions = list(group.permissions.values_list("codename", flat=True))
        assert permissions == [RUN_PROGRAM_PERMISSION, VIEW_PROGRAM_PERMISSION]

    provider = Provider.objects.get_by_name("mockprovider")
    assert provider is not None

    provider_groups = list(provider.admin_groups.values_list("name", flat=True))
    assert provider_groups == ["mockgroup"]

    groups = user.groups.all()
    metadata = getattr(groups[0], "metadata", None)
    assert metadata is None


def test_authentication_only_changes_the_groups_that_changed(settings):
    backend = MockTokenBackend()
    request = MagicMock()
    request.META = {"HTTP_AUTHORIZATION": "Bearer my_awesome_token"}
    settings.SETTINGS_AUTH_MOCK_TOKEN = "my_awesome_token"
    memberships = User.groups.through.objects
    groups_per_request = [
        [AuthenticationGroup(group_name="mockgroup")],
        [AuthenticationGroup(group_name="mockgroup"), AuthenticationGroup(group_name="othergroup")],
        [AuthenticationGroup(group_name="othergroup")],
    ]

    with patch.object(LocalAuthenticationService, "get_groups", side_effect=groups_per_request):
        user, _ = backend.authenticate(request)
        membership_id = memberships.get(user=user, group__name="mockgroup").id

        backend.authenticate(request)
        assert memberships.get(user=user, group__name="mockgroup").id == membership_id

        backend.authenticate(request)
        assert list(user.groups.values_list("name", flat=True)) == ["othergroup"]


def test_incorrect_authorization_header(settings):
    """This test verifies that user is None if the authentication fails."""
    backend = MockTokenBackend()
    request = MagicMock()
    request.META = {"HTTP_AUTHORIZATION": "Bearer my_awesome_token"}

    settings.SETTINGS_AUTH_MOCK_TOKEN = "other_awesome_token"
    with pytest.raises(exceptions.AuthenticationFailed):
        backend.authenticate(request)
