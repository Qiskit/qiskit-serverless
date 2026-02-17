"""This service will manage the access to the 3rd party end-points in IBM Quantum Platform."""

import base64
import hashlib
import json
import logging
from typing import List, Optional, Any

from django.conf import settings
from django.core.cache import cache
from ibm_cloud_sdk_core import ApiException
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from ibm_platform_services import ResourceControllerV2, IamAccessGroupsV2
from rest_framework import exceptions

from api.domain.authentication.authentication_group import AuthenticationGroup
from api.services.authentication.authentication_base import AuthenticationBase

logger = logging.getLogger("gateway.services.authentication.ibm_quantum_platform")


class IBMQuantumPlatform(
    AuthenticationBase
):  # pylint: disable=too-many-instance-attributes
    """
    This class will manage the different access to the different
    end-points that we will make use of them in this service.
    """

    def __init__(self, api_key: str, crn: str):
        self.iam_url = settings.IAM_IBM_CLOUD_BASE_URL
        self.cache_ttl = settings.IAM_IBM_CLOUD_CACHE_TTL
        self.resource_controller_url = settings.RESOURCE_CONTROLLER_IBM_CLOUD_BASE_URL
        self.api_key = api_key
        self.api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        self.crn = crn
        self.authenticator = IAMAuthenticator(apikey=self.api_key, url=self.iam_url)
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
        if self.iam_url is None:
            logger.warning("IAM URL environment variable was not correctly configured.")
            raise exceptions.AuthenticationFailed("You couldn't be authenticated.")

        decoded = self._request_or_cache_jwt_data()

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

        resource_plan_id = self._request_or_cache_resource_plan_id()

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

        if self.account_id is None:
            raise exceptions.AuthenticationFailed("You couldn't be authenticated.")

        group_ids = self._request_or_cache_group_ids()

        return [
            AuthenticationGroup(group_name=group_id, account=self.account_id)
            for group_id in group_ids
        ]

    def _request_or_cache_jwt_data(self) -> Any:
        cache_key = f"auth:jwt:{self.api_key_hash}"
        decoded = cache.get(cache_key)
        if decoded is not None:
            return decoded

        try:
            access_token = self.authenticator.token_manager.get_token()
            decoded = decode_jwt(access_token)
            cache.set(cache_key, decoded, timeout=self.cache_ttl)
        except Exception as ex:  # pylint: disable=broad-exception-caught
            logger.warning("IBM Quantum Platform authentication error: %s.", str(ex))
            raise exceptions.AuthenticationFailed(
                "You couldn't be authenticated, please review your API Key."
            )
        return decoded

    def _request_or_cache_resource_plan_id(self) -> Any:
        cache_key = f"auth:access:{self.crn}:{self.api_key_hash}"
        resource_plan_id = cache.get(cache_key)

        if resource_plan_id is not None:
            return resource_plan_id

        try:
            resource_controller = ResourceControllerV2(self.authenticator)
            resource_controller.set_service_url(self.resource_controller_url)
            instance = resource_controller.get_resource_instance(
                id=self.crn
            ).get_result()
        except ApiException as api_exception:
            logger.warning(
                "IBM Quantum Platform verification error: %s.",
                api_exception.message,
            )
            raise exceptions.AuthenticationFailed(
                "There was a problem in the authentication process with IBM Quantum Platform, please review your CRN."  # pylint: disable=line-too-long
            )

        resource_plan_id = instance.get("resource_plan_id")
        cache.set(cache_key, resource_plan_id, timeout=self.cache_ttl)

        return resource_plan_id

    def _request_or_cache_group_ids(self) -> List[str]:
        cache_key = f"auth:groups:{self.account_id}:{self.api_key_hash}"
        group_ids = cache.get(cache_key)

        if group_ids is not None:
            return group_ids

        try:
            access_groups_service = IamAccessGroupsV2(authenticator=self.authenticator)
            access_groups_service.set_service_url(self.iam_url)
            access_groups_response = access_groups_service.list_access_groups(
                account_id=self.account_id
            ).get_result()
        except ApiException as api_exception:
            logger.warning(
                "IBM Quantum Platform authentication error: %s.", api_exception.message
            )
            return []

        access_groups = access_groups_response.get("groups", [])
        # Remove Public Access from the available groups
        # This group is always available in an account and can be problematic to manage
        access_groups_filtered = [
            access_group
            for access_group in access_groups
            if access_group["name"] != "Public Access"
        ]
        group_ids = [access_group["id"] for access_group in access_groups_filtered]

        cache.set(cache_key, group_ids, timeout=self.cache_ttl)
        return group_ids


def decode_jwt(token: str) -> dict:
    """Decode a JWT token and return the payload as a dictionary."""
    payload = token.split(".")[1]
    padded = payload + "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))
