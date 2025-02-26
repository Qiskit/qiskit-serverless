"""
This file contains e2e tests for Mock Token authentication process
in local environments.
"""


from unittest.mock import MagicMock
from rest_framework.test import APITestCase

from api.authentication import MockAuthBackend


class TestMockTokenAuthentication(APITestCase):
    """
    This class contains e2e tests for Mock Token authentication process
    in local environments.
    """

    def test_mock_auth(self):
        """This test verifies the authentication process for Mock Token."""
        backend = MockAuthBackend()
        request = MagicMock()
        request.META = {"HTTP_AUTHORIZATION": "Bearer my_awesome_token"}

        with self.settings(SETTINGS_AUTH_MOCK_TOKEN="my_awesome_token"):
            user, token = backend.authenticate(request)
            self.assertEqual(user.username, "mockuser")
            self.assertEqual(token.token.decode(), "my_awesome_token")

        with self.settings(SETTINGS_AUTH_MOCK_TOKEN="other_awesome_token"):
            user, token = backend.authenticate(request)
            self.assertIsNone(user)
