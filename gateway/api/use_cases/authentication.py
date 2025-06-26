"""Authentication use case to manage the authentication process in the api."""

import logging
from typing import Optional
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from rest_framework import exceptions

from api.models import RUN_PROGRAM_PERMISSION, VIEW_PROGRAM_PERMISSION
from api.repositories.providers import ProviderRepository
from api.repositories.users import UserRepository
from api.services.authentication.authentication_base import AuthenticationBase
from api.services.authentication.ibm_quantum_platform import IBMQuantumPlatform
from api.services.authentication.local_authentication import LocalAuthenticationService
from api.services.authentication.ibm_quantum import IBMQuantum
from api.domain.authentication.channel import Channel


logger = logging.getLogger("gateway.use_cases.authentication")


class AuthenticationUseCase:  # pylint: disable=too-few-public-methods
    """
    This class will manage the authentication flow for the api.
    """

    user_repository = UserRepository()
    provider_repository = ProviderRepository()

    def __init__(
        self,
        channel: Channel,
        authorization_token: str,
        crn: Optional[str],
        public_access=False,
    ):
        self.channel = channel
        self.authorization_token = authorization_token
        self.crn = crn
        self.public_access = public_access

    def _get_authentication_service_instance(self) -> AuthenticationBase:
        if self.channel in (Channel.IBM_CLOUD, Channel.IBM_QUANTUM_PLATFORM):
            logger.debug("Authentication will be executed with IBM Cloud Quantum Platform.")
            return IBMQuantumPlatform(api_key=self.authorization_token, crn=self.crn)

        if self.channel == Channel.IBM_QUANTUM:
            logger.debug("Authentication will be executed with IQP.")
            return IBMQuantum(authorization_token=self.authorization_token)

        logger.debug("Authentication will be executed with Local service.")
        return LocalAuthenticationService(authorization_token=self.authorization_token)

    def execute(self) -> Optional[type[AbstractUser]]:
        """
        This contains the logic to authenticate and validate the user
        that is doing the request.
        """
        authentication_service = self._get_authentication_service_instance()

        user_id = authentication_service.authenticate()

        if self.public_access is False:
            verified = authentication_service.verify_access()
            if verified is False:
                raise exceptions.AuthenticationFailed(
                    "Sorry, you don't have access to the service."
                )

        access_groups = authentication_service.get_groups()
        quantum_user = self.user_repository.get_or_create_by_id(user_id=user_id)

        if self.channel == Channel.LOCAL:
            permission_names = [VIEW_PROGRAM_PERMISSION, RUN_PROGRAM_PERMISSION]
            groups = self.user_repository.restart_user_groups(
                user=quantum_user,
                authentication_groups=access_groups,
                permission_names=permission_names,
            )
            self.provider_repository.get_or_create_by_name(
                name="mockprovider",
                registry=settings.SETTINGS_AUTH_MOCKPROVIDER_REGISTRY,
                admin_groups=groups,
            )
        else:
            permission_names = [VIEW_PROGRAM_PERMISSION]
            self.user_repository.restart_user_groups(
                user=quantum_user,
                authentication_groups=access_groups,
                permission_names=permission_names,
            )

        return quantum_user
