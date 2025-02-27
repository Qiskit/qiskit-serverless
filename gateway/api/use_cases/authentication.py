"""Authentication use case to manage the authentication process in the api."""

import logging
from django.contrib.auth.models import AbstractUser

from api.repositories.users import UserRepository
from api.services.authentication.authentication_base import AuthenticationBase
from api.services.authentication.ibm_cloud import IBMCloudService
from api.services.authentication.quantum_platform import QuantumPlatformService


logger = logging.getLogger("gateway.use_cases.authentication")


class AuthenticationUseCase:  # pylint: disable=too-few-public-methods
    """
    This class will manage the authentication flow for the api.
    """

    user_repository = UserRepository()

    def __init__(self, authorization_token: str, crn: str | None):
        self.authorization_token = authorization_token
        self.crn = crn

    def _get_authentication_service_instance(self) -> AuthenticationBase:
        if self.crn:
            logger.debug("Authentication will be executed with IBM Cloud")
            return IBMCloudService(api_key=self.authorization_token, crn=self.crn)

        logger.debug("Authentication will be executed with Quantum Platform")
        return QuantumPlatformService(authorization_token=self.authorization_token)

    def execute(self) -> type[AbstractUser] | None:
        """
        This contains the logic to authenticate and validate the user
        that is doing the request.
        """
        authentication_service = self._get_authentication_service_instance()

        user_id = authentication_service.authenticate()
        if user_id is None:
            return None

        verified = authentication_service.verify_access()
        if verified is False:
            return None

        access_groups = authentication_service.get_groups()

        quantum_user = self.user_repository.get_or_create_by_id(user_id=user_id)
        self.user_repository.restart_user_groups(
            user=quantum_user, unique_group_names=access_groups
        )

        return quantum_user
