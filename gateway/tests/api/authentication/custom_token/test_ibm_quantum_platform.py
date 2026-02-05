"""This file contains e2e tests for IBM Quantum Platform authentication process."""

import time
from unittest.mock import MagicMock, patch

import jwt
import responses
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWK
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APITestCase
from ibm_platform_services import IamAccessGroupsV2, ResourceControllerV2
from ibm_cloud_sdk_core import DetailedResponse

from django.contrib.auth import get_user_model

from api.authentication import CustomTokenBackend
from api.domain.authentication.custom_authentication import CustomAuthentication
from api.models import VIEW_PROGRAM_PERMISSION

User = get_user_model()

_test_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_test_public_key = _test_private_key.public_key()


def _create_mock_jwt(iam_id: str, account_id: str) -> str:
    """Create a mock JWT token signed with test RSA key."""
    current_time = int(time.time())
    payload = {
        "iam_id": iam_id,
        "account": {"bss": account_id},
        "iat": current_time,
        "exp": current_time + 3600,
    }
    return jwt.encode(
        payload,
        _test_private_key,
        algorithm="RS256",
        headers={"kid": "test-key-id"},
    )


def _mock_get_signing_key_from_jwt(self, token: str):
    """Mock function that returns the test public key for any token."""
    return PyJWK.from_dict(
        {
            "kty": "RSA",
            "kid": "test-key-id",
            "use": "sig",
            "n": jwt.utils.base64url_encode(
                _test_public_key.public_numbers().n.to_bytes(256, byteorder="big")
            ).decode(),
            "e": jwt.utils.base64url_encode(
                _test_public_key.public_numbers().e.to_bytes(3, byteorder="big")
            ).decode(),
        }
    )


class TestIBMQuantumPlatformAuthentication(APITestCase):
    """This class contains e2e tests for IBM Quantum Platform authentication process."""

    @patch("jwt.PyJWKClient.get_signing_key_from_jwt", _mock_get_signing_key_from_jwt)
    @patch.object(IamAccessGroupsV2, "list_access_groups")
    @patch.object(ResourceControllerV2, "get_resource_instance")
    @responses.activate
    def test_default_authentication_workflow(
        self,
        mock_get_resource_instance: MagicMock,
        mock_list_access_groups: MagicMock,
    ):
        """This test verifies the entire flow of the custom token authentication"""

        mock_get_resource_instance.return_value = DetailedResponse(
            response={"resource_plan_id": "plan-id-123"},
            headers={},
            status_code=200,
        )

        mock_list_access_groups.return_value = DetailedResponse(
            response={"groups": [{"id": "group-id-456", "name": "Private Group"}]},
            headers={},
            status_code=200,
        )

        mock_jwt = _create_mock_jwt(iam_id="IBMid-abc", account_id="account-id-832")
        responses.add(
            responses.POST,
            "https://base-url-mock/identity/token",
            json={"access_token": mock_jwt, "token_type": "Bearer", "expires_in": 3600},
            status=200,
        )

        custom_auth = CustomTokenBackend()
        request = MagicMock()
        request.META = {
            "HTTP_SERVICE_CHANNEL": "ibm_quantum_platform",
            "HTTP_AUTHORIZATION": "Bearer AWESOME_TOKEN",
            "HTTP_SERVICE_CRN": "AWESOME_CRN",
        }

        with self.settings(
            IAM_IBM_CLOUD_BASE_URL="https://base-url-mock",
            RESOURCE_CONTROLLER_IBM_CLOUD_BASE_URL="https://resource-controller.mock",
            RESOURCE_PLANS_ID_ALLOWED=["plan-id-123"],
        ):
            user, authentication = custom_auth.authenticate(request)

            self.assertEqual(user.username, "IBMid-abc")
            self.assertIsInstance(authentication, CustomAuthentication)
            self.assertEqual(authentication.channel, "ibm_quantum_platform")
            self.assertEqual(authentication.token, b"AWESOME_TOKEN")
            self.assertEqual(authentication.instance, "AWESOME_CRN")

            groups_names = user.groups.values_list("name", flat=True).distinct()
            groups_names_list = list(groups_names)
            self.assertListEqual(groups_names_list, ["group-id-456"])

            groups = user.groups.all()
            for group in groups:
                self.assertEqual(group.metadata.account, "account-id-832")

            for group in user.groups.all():
                permissions = list(group.permissions.values_list("codename", flat=True))
                self.assertEqual(permissions, [VIEW_PROGRAM_PERMISSION])

    @patch("jwt.PyJWKClient.get_signing_key_from_jwt", _mock_get_signing_key_from_jwt)
    @patch.object(IamAccessGroupsV2, "list_access_groups")
    @patch.object(ResourceControllerV2, "get_resource_instance")
    @responses.activate
    def test_default_authentication_workflow_with_inactive_account(
        self,
        mock_get_resource_instance: MagicMock,
        mock_list_access_groups: MagicMock,
    ):
        """
        This test verifies the entire flow of the custom token authentication
        for a deactivated user.
        """

        User.objects.create_user(username="no-active", email="a@t.com", is_active=False)

        mock_get_resource_instance.return_value = DetailedResponse(
            response={"resource_plan_id": "plan-id-123"},
            headers={},
            status_code=200,
        )

        mock_list_access_groups.return_value = DetailedResponse(
            response={"groups": [{"id": "group-id-456", "name": "Private Group"}]},
            headers={},
            status_code=200,
        )

        mock_jwt = _create_mock_jwt(iam_id="no-active", account_id="account-id-832")
        responses.add(
            responses.POST,
            "https://base-url-mock/identity/token",
            json={"access_token": mock_jwt, "token_type": "Bearer", "expires_in": 3600},
            status=200,
        )

        custom_auth = CustomTokenBackend()
        request = MagicMock()
        request.META = {
            "HTTP_SERVICE_CHANNEL": "ibm_quantum_platform",
            "HTTP_AUTHORIZATION": "Bearer AWESOME_TOKEN",
            "HTTP_SERVICE_CRN": "AWESOME_CRN",
        }

        with self.settings(
            IAM_IBM_CLOUD_BASE_URL="https://base-url-mock",
            RESOURCE_CONTROLLER_IBM_CLOUD_BASE_URL="https://resource-controller.mock",
            RESOURCE_PLANS_ID_ALLOWED=["plan-id-123"],
        ):
            self.assertRaisesMessage(
                AuthenticationFailed,
                "Your user was deactivated. Please contact to IBM support for reactivaton.",
                custom_auth.authenticate,
                request,
            )
