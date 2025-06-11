"""This file contains e2e tests for Quantum Platform authentication process."""

from unittest.mock import MagicMock, patch
import responses
from rest_framework import exceptions
from rest_framework.test import APITestCase

from api.authentication import CustomTokenBackend
from api.domain.authentication.custom_authentication import CustomAuthentication
from api.models import VIEW_PROGRAM_PERMISSION
from api.services.authentication.quantum_platform import QuantumPlatformService


class TestQuantumPlatformAuthentication(APITestCase):
    """This class contains e2e tests for Quantum Platform authentication process."""

    network_configuration_without_project = [
        {
            "name": "ibm-q",
            "groups": {
                "open": {
                    "name": "open",
                }
            },
        }
    ]

    @responses.activate
    @patch.object(QuantumPlatformService, "_get_network")
    def test_custom_token_authentication(self, get_network_mock: MagicMock):
        """This test verifies the entire flow of the custom token authentication"""

        get_network_mock.return_value = self.network_configuration_without_project

        responses.add(
            responses.POST,
            "http://token_auth_url/api/users/loginWithToken",
            json={"userId": "AwesomeUser", "id": "requestId"},
            status=200,
        )

        responses.add(
            responses.GET,
            "http://token_auth_url/api/users/me",
            json={"is_valid": True},
            status=200,
        )

        custom_auth = CustomTokenBackend()
        request = MagicMock()
        request.META = {"HTTP_AUTHORIZATION": "Bearer AWESOME_TOKEN"}

        with self.settings(
            QUANTUM_PLATFORM_API_BASE_URL="http://token_auth_url/api",
            SETTINGS_TOKEN_AUTH_VERIFICATION_FIELD="is_valid",
        ):
            user, authentication = custom_auth.authenticate(request)
            groups_names = user.groups.values_list("name", flat=True).distinct()
            groups_names_list = list(groups_names)

            self.assertIsInstance(authentication, CustomAuthentication)
            self.assertEqual(authentication.channel, "ibm_quantum")
            self.assertEqual(authentication.token, b"AWESOME_TOKEN")
            self.assertEqual(authentication.instance, None)

            self.assertEqual(user.username, "AwesomeUser")
            self.assertListEqual(groups_names_list, ["ibm-q", "ibm-q/open"])

            groups = user.groups.all()
            for group in groups:
                metadata = getattr(groups, "metadata", None)
                self.assertIsNone(metadata)

            for group in user.groups.all():
                permissions = list(group.permissions.values_list("codename", flat=True))
                self.assertEqual(permissions, [VIEW_PROGRAM_PERMISSION])

    @responses.activate
    def test_with_nested_verification_fields(self):
        """
        This test verifies the entire flow of the custom token authentication
        with the difference that we validate a more complex verification field.
        """
        responses.add(
            responses.POST,
            "http://token_auth_url/api/users/loginWithToken",
            json={"userId": "AwesomeUser", "id": "requestId"},
            status=200,
        )

        responses.add(
            responses.GET,
            "http://token_auth_url/api/users/me",
            json={"is_valid": True, "other": {"nested": {"field": "something_here"}}},
            status=200,
        )

        custom_auth = CustomTokenBackend()
        request = MagicMock()
        request.META = {"HTTP_AUTHORIZATION": "Bearer AWESOME_TOKEN"}

        with self.settings(
            QUANTUM_PLATFORM_API_BASE_URL="http://token_auth_url/api",
            SETTINGS_TOKEN_AUTH_VERIFICATION_FIELD="is_valid;other,nested,field",
        ):
            user, authentication = custom_auth.authenticate(request)

            self.assertIsInstance(authentication, CustomAuthentication)
            self.assertEqual(authentication.channel, "ibm_quantum")
            self.assertEqual(authentication.token, b"AWESOME_TOKEN")
            self.assertEqual(authentication.instance, None)

            self.assertEqual(user.username, "AwesomeUser")

        with self.settings(
            QUANTUM_PLATFORM_API_BASE_URL="http://token_auth_url/api",
            SETTINGS_TOKEN_AUTH_VERIFICATION_FIELD="is_valid;other,WRONG_NESTED_FIELD",
        ):
            self.assertRaises(
                exceptions.AuthenticationFailed,
                custom_auth.authenticate,
                request,
            )

        responses.add(
            responses.GET,
            "http://token_auth_url/api/users/me",
            json={"is_valid": True, "other": "no nested fields"},
            status=200,
        )

        with self.settings(
            QUANTUM_PLATFORM_API_BASE_URL="http://token_auth_url/api",
            SETTINGS_TOKEN_AUTH_VERIFICATION_FIELD="is_valid;other,nested,field",
        ):
            # this should raise an error as `SETTINGS_TOKEN_AUTH_VERIFICATION_FIELD`
            # is not configured properly
            with self.assertRaises(AttributeError):
                custom_auth.authenticate(request)
