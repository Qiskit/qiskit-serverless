"""This service will manage the access to the 3rd party end-points in IBM Quantum Platform."""

import logging
from typing import List, Optional

import jwt
from jwt import PyJWKClient
from django.conf import settings
from ibm_cloud_sdk_core import ApiException
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from ibm_platform_services import ResourceControllerV2, IamAccessGroupsV2
from rest_framework import exceptions

from api.domain.authentication.authentication_group import AuthenticationGroup
from api.services.authentication.authentication_base import AuthenticationBase

logger = logging.getLogger("gateway.services.authentication.ibm_quantum_platform")


class IBMQuantumPlatform(AuthenticationBase):
    """
    This class will manage the different access to the different
    end-points that we will make use of them in this service.
    """

    jwks_client = PyJWKClient(f"{settings.IAM_IBM_CLOUD_BASE_URL}/identity/keys")

    def __init__(self, api_key: str, crn: str):
        if settings.IAM_IBM_CLOUD_BASE_URL is None:
            logger.warning("IAM_IBM_CLOUD_BASE_URL environment variable missing.")
            raise exceptions.AuthenticationFailed("You couldn't be authenticated.")

        if settings.RESOURCE_CONTROLLER_IBM_CLOUD_BASE_URL is None:
            logger.warning(
                "RESOURCE_CONTROLLER_IBM_CLOUD_BASE_URL environment variable missing."
            )
            raise exceptions.AuthenticationFailed("You couldn't be authenticated.")

        self.api_key = api_key
        self.crn = crn
        self.authenticator = IAMAuthenticator(
            apikey=self.api_key, url=settings.IAM_IBM_CLOUD_BASE_URL
        )
        self.access_groups_service = IamAccessGroupsV2(authenticator=self.authenticator)
        self.access_groups_service.set_service_url(settings.IAM_IBM_CLOUD_BASE_URL)

        self.resource_controller = ResourceControllerV2(self.authenticator)
        self.resource_controller.set_service_url(
            settings.RESOURCE_CONTROLLER_IBM_CLOUD_BASE_URL
        )

        self.account_id: Optional[str] = None
        self.iam_id: Optional[str] = None

    def authenticate(self) -> Optional[str]:
        """
        This method authenticates the user with the token provided in the
        instantiation of the class and populates the account_id and
        the iam_id attributes.

        Ideally this method should be called first.

        Returns:
            str: the iam_id of the authenticated user
            None: in case the authentication failed
        """

        try:
            access_token = self.authenticator.token_manager.get_token()
            signing_key = IBMQuantumPlatform.jwks_client.get_signing_key_from_jwt(
                access_token
            )
            decoded = jwt.decode(
                access_token,
                signing_key.key,
                algorithms=["RS256"],
                options={"verify_exp": True, "verify_iat": True},
            )

        except Exception as ex:  # pylint: disable=broad-exception-caught
            logger.warning("IBM Quantum Platform authentication error: %s.", str(ex))
            raise exceptions.AuthenticationFailed(
                "You couldn't be authenticated, please review your API Key."
            )

        self.iam_id = decoded.get("iam_id")
        if self.iam_id is None:
            logger.warning(
                "IBM Quantum Platform didn't return the IAM ID for the user."
            )
            raise exceptions.AuthenticationFailed(
                (
                    "There was a problem in the authentication process with IBM Quantum Platform, "
                    "please try later."
                )
            )

        account_data = decoded.get("account")
        if account_data is None:
            logger.warning(
                "IBM Quantum Platform didn't return the Account data for the user."
            )
            raise exceptions.AuthenticationFailed(
                (
                    "There was a problem in the authentication process with IBM Quantum Platform, "
                    "please try later."
                )
            )

        self.account_id = account_data.get("bss")
        if self.account_id is None:
            logger.warning(
                "IBM Quantum Platform didn't return the Account ID for the user."
            )
            raise exceptions.AuthenticationFailed(
                (
                    "There was a problem in the authentication process with IBM Quantum Platform, "
                    "please try later."
                )
            )

        logger.debug(
            "User authenticated with account_id[%s] and iam_id[%s]",
            self.account_id,
            self.iam_id,
        )

        return self.iam_id

    def verify_access(self) -> bool:
        """
        This method validates that the user has access to Quantum Functions.
        For IBM Quantum Platform this means that the CRN is from an allowed resource_plan

        Returns:
            bool: True or False if the user has or no access
        """

        try:
            instance = self.resource_controller.get_resource_instance(
                id=self.crn
            ).get_result()
        except ApiException as api_exception:
            logger.warning(
                "IBM Quantum Platform verification error: %s.", api_exception.message
            )
            raise exceptions.AuthenticationFailed(
                "There was a problem in the authentication process with IBM Quantum Platform, please review your CRN."  # pylint: disable=line-too-long
            )

        resource_plan_id = instance.get("resource_plan_id")
        if resource_plan_id is None:
            logger.warning(
                "IBM Quantum Platform didn't return the Resource plan ID for the resource."
            )
            raise exceptions.AuthenticationFailed(
                (
                    "There was a problem in the authentication process with IBM Quantum Platform, "
                    "please try later."
                )
            )

        if resource_plan_id not in settings.RESOURCE_PLANS_ID_ALLOWED:
            logger.warning(
                "User has no access to the service using IBM Quantum Platform, Resource plan ID [%s] is not a valid plan %s.",  # pylint: disable=line-too-long
                resource_plan_id,
                settings.RESOURCE_PLANS_ID_ALLOWED,
            )
            return False
        return True

    def get_groups(self) -> List[AuthenticationGroup]:
        """
        Returns an array of access groups from the IBM Quantum Platform account.

        Returns:
            List of groups the user has access with the next format:
            ["account_id/access_group_name"]
        """

        try:
            access_groups_response = self.access_groups_service.list_access_groups(
                account_id=self.account_id
            ).get_result()
        except ApiException as api_exception:
            logger.warning(
                "IBM Quantum Platform authentication error: %s.", api_exception.message
            )
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
            AuthenticationGroup(group_name=access_group["id"], account=self.account_id)
            for access_group in access_groups_filtered
        ]
