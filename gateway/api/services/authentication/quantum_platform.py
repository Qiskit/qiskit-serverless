"""This service will manage the access to the 3rd party end-points in Quantum platform."""


import logging
from typing import List
from django.conf import settings
import requests

from api.utils import remove_duplicates_from_list, safe_request

logger = logging.getLogger("gateway.services.quantum_platform")


class QuantumPlatformService:
    """
    This class will manage the different access to the different
    end-points that we will make us of them in this service.
    """

    def __init__(self, authorization_token):
        self.auth_url = f"{settings.QUANTUM_PLATFORM_API_BASE_URL}/users/loginWithToken"
        self.verification_url = f"{settings.QUANTUM_PLATFORM_API_BASE_URL}/users/me"
        self.instances_url = f"{settings.IQP_QCON_API_BASE_URL}/network"
        self.authorization_token = authorization_token
        self.access_token = None

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
        """
        if self.auth_url is None:
            logger.warning(
                "Problems authenticating: No auth url: something is broken in our settings."
            )
            return None

        auth_data = safe_request(
            request=lambda: requests.post(
                self.auth_url,
                json={"apiToken": self.authorization_token},
                timeout=60,
            )
        )
        if auth_data is None:
            logger.warning(
                "Problems authenticating: No authorization data returned from auth url."
            )
            return None

        user_id = auth_data.get("userId")
        if user_id is None:
            logger.warning("Problems authenticating: No user id.")
            return None

        self.access_token = auth_data.get("id")
        if self.access_token is None:
            logger.warning("Problems authenticating: No access token.")
            return None

        return user_id

    def verify_access(self) -> bool:
        """
        This method validates that the user has access to Quantum Functions.
        In this specific case the most important validation is the ibmQNetwork
        field.
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
                "Problems authenticating: No verification data returned from request."
            )
            return False

        verifications = []
        verification_fields = settings.SETTINGS_TOKEN_AUTH_VERIFICATION_FIELD.split(";")
        for verification_field in verification_fields:
            nested_field_value = verification_data
            for nested_field in verification_field.split(","):
                nested_field_value = nested_field_value.get(nested_field)
            verifications.append(nested_field_value)

        verified = all(verifications)
        if verified is False:
            logger.warning("Problems authenticating: User is not verified.")

        return verified

    def get_groups(self) -> List[str]:
        """
        Returns an array of instances from network configuration.
        Args:
            network: Quantum User IQP Network configuration

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
