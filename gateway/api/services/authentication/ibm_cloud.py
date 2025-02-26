"""This service will manage the access to the 3rd party end-points in IBM Cloud."""

import logging
from typing import List

from django.conf import settings
from ibm_cloud_sdk_core import ApiException
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from ibm_platform_services import IamIdentityV1, ResourceControllerV2, IamAccessGroupsV2

from api.services.authentication.authentication_base import AuthenticationBase


logger = logging.getLogger("gateway.services.ibm_cloud")


class IBMCloudService(AuthenticationBase):
    """
    This class will manage the different access to the different
    end-points that we will make use of them in this service.
    """

    def __init__(self, api_key: str, crn: str):
        self.iam_url = settings.IAM_IBM_CLOUD_BASE_URL
        self.resource_controller_url = settings.RESOURCE_CONTROLLER_IBM_CLOUD_BASE_URL
        self.api_key = api_key
        self.crn = crn
        self.authenticator = IAMAuthenticator(apikey=self.api_key, url=self.iam_url)
        self.account_id: str | None = None
        self.iam_id: str | None = None

    def authenticate(self) -> str | None:
        """
        This method authenticates the user with the token provided in the
        instantiation of the class and populates the account_id and
        the iam_id attributes.

        Ideally this method should be called first.

        Returns:
            str: the iam_id of the authenticated user
            None: in case the authentication failed
        """
        if self.iam_url is None:
            logger.warning(
                "Problems authenticating: No iam url: something is broken in our settings."
            )
            return None

        iam_identity_service = IamIdentityV1(authenticator=self.authenticator)
        iam_identity_service.set_service_url(self.iam_url)
        try:
            user_info = iam_identity_service.get_api_keys_details(
                iam_api_key=self.api_key, include_history=False
            ).get_result()
        except ApiException as api_exception:
            logger.warning("Problems authenticating: %s.", api_exception.message)
            return None

        self.account_id = user_info.get("account_id")
        self.iam_id = user_info.get("iam_id")

        return self.iam_id

    def verify_access(self) -> bool:
        """
        This method validates that the user has access to Quantum Functions.
        For IBM Cloud this means that the CRN is from an allowed resource_plan

        Returns:
            bool: True or False if the user has or no access
        """

        resource_controller = ResourceControllerV2(self.authenticator)
        resource_controller.set_service_url(self.resource_controller_url)
        try:
            instance = resource_controller.get_resource_instance(
                id=self.crn
            ).get_result()
        except ApiException as api_exception:
            logger.warning("Problems authenticating: %s.", api_exception.message)
            return False

        resource_plan_id = instance.get("resource_plan_id")
        if resource_plan_id not in settings.RESOURCE_PLANS_ID_ALLOWED:
            logger.warning(
                "Problems authenticating: Resource plan id [%s] is not a valid plan.",
                resource_plan_id,
            )
            return False
        return True

    def get_groups(self) -> List[str]:
        """
        Returns an array of access groups from the IBM Cloud account.

        Returns:
            List of groups the user has access with the next format:
            ["account_id/access_group_name"]
        """

        access_groups_service = IamAccessGroupsV2(authenticator=self.authenticator)
        access_groups_service.set_service_url(self.iam_url)

        try:
            access_groups_response = access_groups_service.list_access_groups(
                account_id=self.account_id
            ).get_result()
        except ApiException as api_exception:
            logger.warning("Problems authenticating: %s.", api_exception.message)
            return []

        access_groups = access_groups_response.get("groups", [])
        # Remove Public Access from the available groups
        # This group is always available in an account and can be
        # problematic to manage
        access_groups_filtered = [
            access_group
            for access_group in access_groups
            if access_group["name"] != "Public Access"
        ]
        return [
            f"{self.account_id}/{access_group['name']}"
            for access_group in access_groups_filtered
        ]
