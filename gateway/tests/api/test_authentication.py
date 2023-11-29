"""Tests authentication."""
from unittest.mock import MagicMock

import responses
from rest_framework.test import APITestCase

from api.authentication import CustomTokenBackend, CustomToken, MockAuthBackend


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

    @responses.activate
    def test_with_nested_verification_fields(self):
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
            json={"is_valid": True, "other": {"nested": {"field": "something_here"}}},
            status=200,
        )

        custom_auth = CustomTokenBackend()
        request = MagicMock()
        request.META.get.return_value = "Bearer AWESOME_TOKEN"

        with self.settings(
            SETTINGS_TOKEN_AUTH_URL="http://token_auth_url",
            SETTINGS_TOKEN_AUTH_USER_FIELD="userId",
            SETTINGS_TOKEN_AUTH_VERIFICATION_URL="http://token_auth_verification_url",
            SETTINGS_TOKEN_AUTH_VERIFICATION_FIELD="is_valid;other,nested,field",
        ):
            user, token = custom_auth.authenticate(request)

            self.assertIsInstance(token, CustomToken)
            self.assertEqual(token.token, b"AWESOME_TOKEN")

            self.assertEqual(user.username, "AwesomeUser")

        with self.settings(
            SETTINGS_TOKEN_AUTH_URL="http://token_auth_url",
            SETTINGS_TOKEN_AUTH_USER_FIELD="userId",
            SETTINGS_TOKEN_AUTH_VERIFICATION_URL="http://token_auth_verification_url",
            SETTINGS_TOKEN_AUTH_VERIFICATION_FIELD="is_valid;other,WRONG_NESTED_FIELD",
        ):
            user, token = custom_auth.authenticate(request)

            self.assertIsNone(user)
            self.assertEqual(token.token, b"AWESOME_TOKEN")

        responses.add(
            responses.GET,
            "http://token_auth_verification_url",
            json={"is_valid": True, "other": "no nested fields"},
            status=200,
        )

        with self.settings(
            SETTINGS_TOKEN_AUTH_URL="http://token_auth_url",
            SETTINGS_TOKEN_AUTH_USER_FIELD="userId",
            SETTINGS_TOKEN_AUTH_VERIFICATION_URL="http://token_auth_verification_url",
            SETTINGS_TOKEN_AUTH_VERIFICATION_FIELD="is_valid;other,nested,field",
        ):
            # this should raise an error as `SETTINGS_TOKEN_AUTH_VERIFICATION_FIELD`
            # is not configured properly
            with self.assertRaises(AttributeError):
                custom_auth.authenticate(request)

    def test_mock_auth(self):
        """Tests for mock authentication backend."""
        backend = MockAuthBackend()
        request = MagicMock()
        request.META.get.return_value = "Bearer my_awesome_token"

        with self.settings(SETTINGS_AUTH_MOCK_TOKEN="my_awesome_token"):
            user, token = backend.authenticate(request)
            self.assertEqual(user.username, "mock_user")
            self.assertEqual(token.token.decode(), "my_awesome_token")

        with self.settings(SETTINGS_AUTH_MOCK_TOKEN="other_awesome_token"):
            user, token = backend.authenticate(request)
            self.assertIsNone(user)
