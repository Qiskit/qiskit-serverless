"""This file contains e2e tests for IBM Quantum Platform authentication process."""

import base64
import json
import time
from unittest.mock import MagicMock, patch
import responses
from django.conf import settings
from django.core.cache import cache
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APITestCase
from ibm_platform_services import IamAccessGroupsV2, ResourceControllerV2
from ibm_cloud_sdk_core import DetailedResponse

from api.authentication import CustomTokenBackend
from api.domain.authentication.custom_authentication import CustomAuthentication
from core.models import VIEW_PROGRAM_PERMISSION

RESOURCE_PLAN_ID = "test-plan-id"


def _create_mock_jwt(iam_id: str, account_id: str) -> str:
    """Create a mock JWT token with the given iam_id and account_id."""
    current_time = int(time.time())
    header = (
        base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        .decode()
        .rstrip("=")
    )
    payload = (
        base64.urlsafe_b64encode(
            json.dumps(
                {
                    "iam_id": iam_id,
                    "account": {"bss": account_id},
                    "iat": current_time,
                    "exp": current_time + 3600,
                }
            ).encode()
        )
        .decode()
        .rstrip("=")
    )
    signature = "mock_signature"
    return f"{header}.{payload}.{signature}"


def _mock_iam_services(
    mock_get_resource_instance: MagicMock,
    mock_list_access_groups: MagicMock,
    group_id="test-group",
):
    """Configure mock responses for IAM services."""
    mock_get_resource_instance.return_value = DetailedResponse(
        response={"resource_plan_id": RESOURCE_PLAN_ID},
        headers={},
        status_code=200,
    )
    mock_list_access_groups.return_value = DetailedResponse(
        response={
            "groups": [
                {"id": group_id, "name": "Test Group"},
                {"id": group_id, "name": "Public Accesss"},
            ]
        },
        headers={},
        status_code=200,
    )


def _add_mock_response(iam_id: str, account_id: str):
    """Add a mock token response to responses."""
    responses.add(
        responses.POST,
        f"{settings.IAM_IBM_CLOUD_BASE_URL}/identity/token",
        json={
            "access_token": _create_mock_jwt(iam_id, account_id),
            "token_type": "Bearer",
            "expires_in": 3600,
        },
        status=200,
    )


def _create_request(token: str = "any_token", crn: str = "any:crn:123"):
    """Create a mock request that can be used in the authenticate() method"""
    request = MagicMock()
    request.META = {
        "HTTP_SERVICE_CHANNEL": "ibm_quantum_platform",
        "HTTP_AUTHORIZATION": f"Bearer {token}",
        "HTTP_SERVICE_CRN": crn,
    }
    return request


class TestIBMQuantumPlatformAuthentication(APITestCase):
    """E2E tests for IBM Quantum Platform authentication."""

    fixtures = ["tests/fixtures/authentication_fixtures.json"]

    def setUp(self):
        cache.clear()

    @patch.object(IamAccessGroupsV2, "list_access_groups")
    @patch.object(ResourceControllerV2, "get_resource_instance")
    @responses.activate
    def test_default_authentication_workflow(
        self, mock_get_resource_instance: MagicMock, mock_list_access_groups: MagicMock
    ):
        """Verifies the entire flow of the custom token authentication."""
        _mock_iam_services(
            mock_get_resource_instance,
            mock_list_access_groups,
            group_id="AccessGroupId-23afbcd24-00a0-00ab-ab0c-1a23b4c567de",
        )
        _add_mock_response("IBMid-0000000ABC", "abc18abcd41546508b35dfe0627109c4")

        with self.settings(RESOURCE_PLANS_ID_ALLOWED=[RESOURCE_PLAN_ID]):
            user, auth = CustomTokenBackend().authenticate(_create_request())

            self.assertEqual(user.username, "IBMid-0000000ABC")
            self.assertIsInstance(auth, CustomAuthentication)
            self.assertEqual(auth.channel, "ibm_quantum_platform")

            group_names = list(user.groups.values_list("name", flat=True))
            self.assertEqual(
                group_names, ["AccessGroupId-23afbcd24-00a0-00ab-ab0c-1a23b4c567de"]
            )

            for group in user.groups.all():
                self.assertEqual(
                    group.metadata.account, "abc18abcd41546508b35dfe0627109c4"
                )
                permissions = list(group.permissions.values_list("codename", flat=True))
                self.assertEqual(permissions, [VIEW_PROGRAM_PERMISSION])

    @patch.object(IamAccessGroupsV2, "list_access_groups")
    @patch.object(ResourceControllerV2, "get_resource_instance")
    @responses.activate
    def test_inactive_account_raises_error(
        self, mock_get_resource_instance: MagicMock, mock_list_access_groups: MagicMock
    ):
        """Deactivated users should receive an authentication error."""
        _mock_iam_services(mock_get_resource_instance, mock_list_access_groups)
        _add_mock_response("IBMid-1000000XYZ", "abc18abcd41546508b35dfe0627109c4")

        with self.settings(RESOURCE_PLANS_ID_ALLOWED=[RESOURCE_PLAN_ID]):
            self.assertRaisesMessage(
                AuthenticationFailed,
                "Your user was deactivated. Please contact to IBM support for reactivaton.",
                CustomTokenBackend().authenticate,
                _create_request(),
            )

    @patch.object(IamAccessGroupsV2, "list_access_groups")
    @patch.object(ResourceControllerV2, "get_resource_instance")
    @responses.activate
    def test_cache_prevents_duplicate_api_calls(
        self, mock_get_resource_instance: MagicMock, mock_list_access_groups: MagicMock
    ):
        """Second authentication call should use cache, not API."""
        _mock_iam_services(mock_get_resource_instance, mock_list_access_groups)
        _add_mock_response("IBMid-CACHE-TEST", "cache_account")

        auth = CustomTokenBackend()
        request = _create_request()

        with self.settings(RESOURCE_PLANS_ID_ALLOWED=[RESOURCE_PLAN_ID]):
            auth.authenticate(request)
            auth.authenticate(request)

            self.assertEqual(mock_get_resource_instance.call_count, 1)
            self.assertEqual(mock_list_access_groups.call_count, 1)

    @patch.object(IamAccessGroupsV2, "list_access_groups")
    @patch.object(ResourceControllerV2, "get_resource_instance")
    @responses.activate
    def test_different_tokens_use_separate_cache(
        self, mock_get_resource_instance: MagicMock, mock_list_access_groups: MagicMock
    ):
        """Different API keys should have separate cache entries."""
        _mock_iam_services(mock_get_resource_instance, mock_list_access_groups)
        _add_mock_response("IBMid-USER-A", "account_a")
        _add_mock_response("IBMid-USER-B", "account_b")

        auth = CustomTokenBackend()

        with self.settings(RESOURCE_PLANS_ID_ALLOWED=[RESOURCE_PLAN_ID]):
            user_a, _ = auth.authenticate(_create_request(token="TOKEN_A"))
            user_b, _ = auth.authenticate(_create_request(token="TOKEN_B"))

            self.assertEqual(user_a.username, "IBMid-USER-A")
            self.assertEqual(user_b.username, "IBMid-USER-B")
            self.assertEqual(mock_get_resource_instance.call_count, 2)
            self.assertEqual(mock_list_access_groups.call_count, 2)
