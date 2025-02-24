"""Authentication use case to manage the authentication process in the api."""

import logging
from django.contrib.auth.models import AbstractUser

from api.repositories.users import UserRepository
from api.services.authentication.quantum_platform import QuantumPlatformService


logger = logging.getLogger("gateway.use_cases.authentication")


class AuthenticationUseCase:  # pylint: disable=too-few-public-methods
    """
    This class will manage the authentication flow for the api.
    """

    user_repository = UserRepository()

    def __init__(self, authorization_token: str):
        self.authorization_token = authorization_token

    def execute(self) -> type[AbstractUser] | None:
        """
        This contains the logic to authenticate and validate the user
        that is doing the request.
        """
        quantum_platform_service = QuantumPlatformService(
            authorization_token=self.authorization_token
        )
        user_id = quantum_platform_service.authenticate()
        if user_id is None:
            return None

        verified = quantum_platform_service.verify_access()
        if verified is False:
            return None

        access_groups = quantum_platform_service.get_groups()

        quantum_user = self.user_repository.get_or_create_by_id(user_id=user_id)
        self.user_repository.restart_user_groups(
            user=quantum_user, unique_group_names=access_groups
        )

        return quantum_user
