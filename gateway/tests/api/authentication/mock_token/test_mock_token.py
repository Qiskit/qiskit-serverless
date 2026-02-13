"""
This file contains e2e tests for Mock Token authentication process
in local environments.
"""

from unittest.mock import MagicMock
from rest_framework import exceptions
from rest_framework.test import APITestCase

from api.authentication import MockTokenBackend
from core.models import RUN_PROGRAM_PERMISSION, VIEW_PROGRAM_PERMISSION
from api.repositories.providers import ProviderRepository


class TestMockTokenAuthentication(APITestCase):
    """
    This class contains e2e tests for Mock Token authentication process
    in local environments.
    """

    def test_default_authentication_workflow(self):
        """This test verifies the authentication process for Mock Token."""
        backend = MockTokenBackend()
        request = MagicMock()
        request.META = {"HTTP_AUTHORIZATION": "Bearer my_awesome_token"}

        provider_repository = ProviderRepository()

        with self.settings(SETTINGS_AUTH_MOCK_TOKEN="my_awesome_token"):
            user, token = backend.authenticate(request)
            self.assertEqual(user.username, "mockuser")
            self.assertEqual(token.token.decode(), "my_awesome_token")

            for group in user.groups.all():
                permissions = list(group.permissions.values_list("codename", flat=True))
                self.assertEqual(
                    permissions, [RUN_PROGRAM_PERMISSION, VIEW_PROGRAM_PERMISSION]
                )

            provider = provider_repository.get_provider_by_name("mockprovider")
            self.assertIsNotNone(provider)

            provider_groups = list(provider.admin_groups.values_list("name", flat=True))
            self.assertEqual(provider_groups, ["mockgroup"])

            groups = user.groups.all()
            metadata = getattr(groups[0], "metadata", None)
            self.assertIsNone(metadata)

    def test_incorrect_authorization_header(self):
        """This test verifies that user is None if the authentication fails."""
        backend = MockTokenBackend()
        request = MagicMock()
        request.META = {"HTTP_AUTHORIZATION": "Bearer my_awesome_token"}

        with self.settings(SETTINGS_AUTH_MOCK_TOKEN="other_awesome_token"):
            self.assertRaises(
                exceptions.AuthenticationFailed,
                backend.authenticate,
                request,
            )
