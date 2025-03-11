"""This file contains e2e tests for IBM Cloud authentication process."""


from unittest.mock import MagicMock, patch
import responses
from rest_framework.test import APITestCase
from ibm_platform_services import IamAccessGroupsV2, IamIdentityV1, ResourceControllerV2
from ibm_cloud_sdk_core import DetailedResponse

from api.authentication import CustomTokenBackend
from api.domain.authentication.custom_authentication import CustomAuthentication
from api.models import VIEW_PROGRAM_PERMISSION


class TestIBMCloudAuthentication(APITestCase):
    """This class contains e2e tests for Quantum Platform authentication process."""

    @patch.object(IamAccessGroupsV2, "list_access_groups")
    @patch.object(ResourceControllerV2, "get_resource_instance")
    @patch.object(IamIdentityV1, "get_api_keys_details")
    @responses.activate
    def test_default_authentication_workflow(
        self,
        mock_get_api_keys_details: MagicMock,
        mock_get_resource_instance: MagicMock,
        mock_list_access_groups: MagicMock,
    ):
        """This test verifies the entire flow of the custom token authentication"""

        mock_get_api_keys_details.return_value = DetailedResponse(
            response={
                "iam_id": "IBMid-0000000ABC",
                "account_id": "abc18abcd41546508b35dfe0627109c4",
            },
            headers={},
            status_code=200,
        )

        mock_get_resource_instance.return_value = DetailedResponse(
            response={
                "resource_plan_id": "f04b2f00-35b0-46b0-b84d-eb63418417e6",
            },
            headers={},
            status_code=200,
        )

        mock_list_access_groups.return_value = DetailedResponse(
            response={
                "groups": [
                    {
                        "id": "AccessGroupId-23afbcd24-00a0-00ab-ab0c-1a23b4c567de",
                        "name": "Private Group",
                    }
                ],
            },
            headers={},
            status_code=200,
        )

        responses.add(
            responses.POST,
            "https://iam.test.cloud.ibm.com/identity/token",
            json={
                "iam_id": "IBMid-0000000ABC",
                "account_id": "abc18abcd41546508b35dfe0627109c4",
            },
            status=200,
        )

        custom_auth = CustomTokenBackend()
        request = MagicMock()
        request.META = {
            "HTTP_AUTHORIZATION": "Bearer AWESOME_TOKEN",
            "HTTP_SERVICE_CRN": "AWESOME_CRN",
        }

        with self.settings(
            IAM_IBM_CLOUD_BASE_URL="https://iam.test.cloud.ibm.com",
            RESOURCE_CONTROLLER_IBM_CLOUD_BASE_URL="https://resource-controller.test.cloud.ibm.com",
            RESOURCE_PLANS_ID_ALLOWED=["f04b2f00-35b0-46b0-b84d-eb63418417e6"],
        ):
            user, authentication = custom_auth.authenticate(request)

            self.assertEqual(user.username, "IBMid-0000000ABC")
            self.assertIsInstance(authentication, CustomAuthentication)
            self.assertEqual(authentication.channel, "ibm_cloud")
            self.assertEqual(authentication.token, b"AWESOME_TOKEN")
            self.assertEqual(authentication.instance, "AWESOME_CRN")

            groups_names = user.groups.values_list("name", flat=True).distinct()
            groups_names_list = list(groups_names)
            self.assertListEqual(
                groups_names_list,
                ["AccessGroupId-23afbcd24-00a0-00ab-ab0c-1a23b4c567de"],
            )

            groups = user.groups.all()
            for group in groups:
                self.assertEqual(
                    group.metadata.account, "abc18abcd41546508b35dfe0627109c4"
                )

            for group in user.groups.all():
                permissions = list(group.permissions.values_list("codename", flat=True))
                self.assertEqual(permissions, [VIEW_PROGRAM_PERMISSION])
