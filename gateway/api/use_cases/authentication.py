"""Authentication use case to manage the authentication process in the api."""

import logging
from django.conf import settings
from django.contrib.auth.models import AbstractUser

from api.models import RUN_PROGRAM_PERMISSION, VIEW_PROGRAM_PERMISSION
from api.repositories.providers import ProviderRepository
from api.repositories.users import UserRepository
from api.services.authentication.authentication_base import AuthenticationBase
from api.services.authentication.ibm_cloud import IBMCloudService
from api.services.authentication.local_authentication import LocalAuthenticationService
from api.services.authentication.quantum_platform import QuantumPlatformService
from api.use_cases.enums.channel import Channel


logger = logging.getLogger("gateway.use_cases.authentication")


class AuthenticationUseCase:  # pylint: disable=too-few-public-methods
    """
    This class will manage the authentication flow for the api.
    """

    user_repository = UserRepository()
    provider_repository = ProviderRepository()

    def __init__(self, channel: Channel, authorization_token: str, crn: str | None):
        self.channel = channel
        self.authorization_token = authorization_token
        self.crn = crn

    def _get_authentication_service_instance(self) -> AuthenticationBase:
        if self.channel == Channel.IBM_CLOUD:
            logger.debug("Authentication will be executed with IBM Cloud")
            return IBMCloudService(api_key=self.authorization_token, crn=self.crn)

        if self.channel == Channel.IBM_QUANTUM:
            logger.debug("Authentication will be executed with Quantum Platform")
            return QuantumPlatformService(authorization_token=self.authorization_token)

        logger.debug("Authentication will be executed with Local service")
        return LocalAuthenticationService(authorization_token=self.authorization_token)

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

        if self.channel == Channel.LOCAL:
            permission_names = [VIEW_PROGRAM_PERMISSION, RUN_PROGRAM_PERMISSION]
            groups = self.user_repository.restart_user_groups(
                user=quantum_user,
                unique_group_names=access_groups,
                permission_names=permission_names,
            )
            self.provider_repository.create(
                name="mockprovider",
                registry=settings.SETTINGS_AUTH_MOCKPROVIDER_REGISTRY,
                admin_groups=groups,
            )
        else:
            permission_names = [VIEW_PROGRAM_PERMISSION]
            self.user_repository.restart_user_groups(
                user=quantum_user,
                unique_group_names=access_groups,
                permission_names=permission_names,
            )

        return quantum_user
