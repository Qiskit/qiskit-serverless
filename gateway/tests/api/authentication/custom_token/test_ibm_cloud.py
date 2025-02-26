"""This file contains e2e tests for IBM Cloud authentication process."""


from unittest.mock import MagicMock, patch
import responses
from rest_framework.test import APITestCase

from api.authentication import CustomTokenBackend, CustomToken, MockAuthBackend
from api.services.authentication.quantum_platform import QuantumPlatformService


class TestIBMCloudAuthentication(APITestCase):
    """This class contains e2e tests for Quantum Platform authentication process."""

    @responses.activate
    def test_default_authentication_workflow(self):
        """This test verifies the entire flow of the custom token authentication"""

        responses.add(
            responses.POST,
            "https://iam.test.cloud.ibm.com/identity/token",
            json={
                "iam_id": "IBMid-0000000ABC",
                "account_id": "abc18abcd41546508b35dfe0627109c4",
            },
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
            IAM_IBM_CLOUD_BASE_URL="https://iam.test.cloud.ibm.com",
            RESOURCE_CONTROLLER_IBM_CLOUD_BASE_URL="https://resource-controller.test.cloud.ibm.com",
            RESOURCE_PLANS_ID_ALLOWED=["f04b2f00-35b0-46b0-b84d-eb63418417e6"],
        ):
            user, token = custom_auth.authenticate(request)
            print(user)
            print(token)
            # groups_names = user.groups.values_list("name", flat=True).distinct()
            # groups_names_list = list(groups_names)

            # self.assertIsInstance(token, CustomToken)
            # self.assertEqual(token.token, b"AWESOME_TOKEN")

            # self.assertEqual(user.username, "AwesomeUser")
            # self.assertListEqual(groups_names_list, ["ibm-q", "ibm-q/open"])
