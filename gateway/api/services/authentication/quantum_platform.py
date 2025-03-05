"""This service will manage the access to the 3rd party end-points in Quantum platform."""


import logging
from typing import List
from django.conf import settings
import requests
from rest_framework import exceptions

from api.services.authentication.authentication_base import AuthenticationBase
from api.utils import remove_duplicates_from_list, safe_request

logger = logging.getLogger("gateway.services.authentication.quantum_platform")


class QuantumPlatformService(AuthenticationBase):
    """
    This class will manage the different access to the different
    end-points that we will make use of them in this service.
    """

    def __init__(self, authorization_token: str):
        self.auth_url = f"{settings.QUANTUM_PLATFORM_API_BASE_URL}/users/loginWithToken"
        self.verification_url = f"{settings.QUANTUM_PLATFORM_API_BASE_URL}/users/me"
        self.instances_url = f"{settings.IQP_QCON_API_BASE_URL}/network"
        self.authorization_token = authorization_token
        self.access_token: str | None = None

    def _get_network(self, access_token: str):
        """Obtain network configuration for a specific user:
        Args:
            access_token: IQP user token

        Returns:
            network: {
                name: str,
                groups: {
                    str: {
                        name:
                        projects: {
                            str: {
                                name: str
                            }
                        }
                    }
                }
            }
        """
        logger.debug("Get Network information from [%s]", self.instances_url)
        if self.instances_url is None:
            return []

        return safe_request(
            request=lambda: requests.get(
                self.instances_url,
                headers={"Authorization": access_token},
                timeout=60,
            )
        )

    def _get_instances_from_network(self, network) -> List[str]:
        """
        Returns an array of instances from network configuration.
        Args:
            network: Quantum User IQP Network configuration

        Returns:
            List of instances, ex:
            ["hub/group/project"] -> ["hub", "hub/project", "hub/project/group"]
        """
        instances = []
        if network:  # pylint: disable=too-many-nested-blocks
            logger.debug("Network exists, generate instances from network")
            for hub in network:
                instances.append(hub.get("name"))
                groups = hub.get("groups")
                if groups:
                    for group in groups.values():
                        instances.append(f"{hub.get('name')}/{group.get('name')}")
                        projects = group.get("projects")
                        if projects:
                            for project in projects.values():
                                instances.append(
                                    f"{hub.get('name')}/{group.get('name')}/{project.get('name')}"
                                )
        return instances

    def authenticate(self) -> str | None:
        """
        This method authenticates the user with the token provided in the
        instantiation of the class and populates the access_token attribute.

        Ideally this method should be called first.

        Returns:
            str: the user_id of the authenticated user
            None: in case the authentication failed
        """
        if self.auth_url is None:
            logger.warning(
                "Authentication url is not correctly configured."
            )
            raise exceptions.AuthenticationFailed("You couldn't be authenticated.")

        auth_data = safe_request(
            request=lambda: requests.post(
                self.auth_url,
                json={"apiToken": self.authorization_token},
                timeout=60,
            )
        )
        if auth_data is None:
            logger.warning(
                "Quantum Platform returned no data for the specific user. Probably the token is not valid."
            )
            raise exceptions.AuthenticationFailed("You couldn't be authenticated, please review your token.")

        user_id = auth_data.get("userId")
        if user_id is None:
            logger.warning("Quantum Platform didn't return the id for the user.")
            raise exceptions.AuthenticationFailed("There was a problem in the autentication process with Quantum Platform, please try later.")

        self.access_token = auth_data.get("id")
        if self.access_token is None:
            logger.warning("Quantum Platform didn't return the access token for the user")
            raise exceptions.AuthenticationFailed("There was a problem in the autentication process with Quantum Platform, please try later.")

        return user_id

    def verify_access(self) -> bool:
        """
        This method validates that the user has access to Quantum Functions.
        In this specific case the most important validation is the ibmQNetwork
        field.

        Returns:
            bool: True or False if the user has or no access
        """
        verification_data = safe_request(
            request=lambda: requests.get(
                self.verification_url,
                headers={"Authorization": self.access_token},
                timeout=60,
            )
        )
        if verification_data is None:
            logger.warning(
                "Quantum Platform didn't return user data to verify."
            )
            raise exceptions.AuthenticationFailed("There was a problem in the autentication process with Quantum Platform, please try later.")

        verifications = []
        verification_fields = settings.SETTINGS_TOKEN_AUTH_VERIFICATION_FIELD.split(";")
        for verification_field in verification_fields:
            nested_field_value = verification_data
            for nested_field in verification_field.split(","):
                nested_field_value = nested_field_value.get(nested_field)
            verifications.append(nested_field_value)

        verified = all(verifications)
        if verified is False:
            logger.warning("User has no access to the service using Quantum Platform.")

        return verified

    def get_groups(self) -> List[str]:
        """
        Returns an array of instances from network configuration.

        Returns:
            List of instances, ex:
            ["hub/group/project"] -> ["hub", "hub/project", "hub/project/group"]
        """
        network = self._get_network(self.access_token)
        instances = self._get_instances_from_network(network)

        # Initially the list generated should not contain duplicates
        # but this is just to sanitize the entry
        logger.debug("Remove duplicates from instances")
        return remove_duplicates_from_list(instances)
