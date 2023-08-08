"""Tests authentication."""
from unittest.mock import MagicMock

import responses
from rest_framework.test import APITestCase

from api.authentication import CustomTokenBackend, CustomToken


class TestAuthentication(APITestCase):
    """Tests authentication."""

    @responses.activate
    def test_custom_token_authentication(self):
        """Tests custom token auth."""
        responses.add(
            responses.POST,
            "http://token_auth_url",
            json={"userId": "AwesomeUser", "id": "requestId"},
            status=200,
        )

        responses.add(
            responses.GET,
            "http://token_auth_verification_url",
            json={"is_valid": True},
            status=200,
        )

        custom_auth = CustomTokenBackend()
        request = MagicMock()
        request.META.get.return_value = "Bearer AWESOME_TOKEN"

        with self.settings(
            SETTINGS_TOKEN_AUTH_URL="http://token_auth_url",
            SETTINGS_TOKEN_AUTH_USER_FIELD="userId",
            SETTINGS_TOKEN_AUTH_VERIFICATION_URL="http://token_auth_verification_url",
            SETTINGS_TOKEN_AUTH_VERIFICATION_FIELD="is_valid",
        ):
            user, token = custom_auth.authenticate(request)

            self.assertIsInstance(token, CustomToken)
            self.assertEqual(token.token, b"AWESOME_TOKEN")

            self.assertEqual(user.username, "AwesomeUser")
