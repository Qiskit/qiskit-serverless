"""Authentication use case to manage the authentication process in the api."""

import logging
from typing import List

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser, Group, Permission
from rest_framework import exceptions

from api.access_policies.users import UserAccessPolicies
from api.domain.authentication.authentication_group import AuthenticationGroup
from api.domain.authentication.channel import Channel
from api.services.authentication.ibm_quantum_platform import IBMQuantumPlatform
from api.services.authentication.local_authentication import LocalAuthenticationService
from core.models import GroupMetadata, RUN_PROGRAM_PERMISSION, VIEW_PROGRAM_PERMISSION, Provider

User = get_user_model()
logger = logging.getLogger("api.AuthenticationUseCase")


class AuthenticationUseCase:
    """This class will manage the authentication flow for the api."""

    def __init__(self, channel, authorization_token, crn, public_access=False):
        self.channel = channel
        self.authorization_token = authorization_token
        self.crn = crn
        self.public_access = public_access

    def _get_authentication_service_instance(self):
        if self.channel in (Channel.IBM_CLOUD, Channel.IBM_QUANTUM_PLATFORM):
            return IBMQuantumPlatform(api_key=self.authorization_token, crn=self.crn)
        return LocalAuthenticationService(authorization_token=self.authorization_token)

    def execute(self):
        """This contains the logic to authenticate and validate the user."""
        authentication_service = self._get_authentication_service_instance()

        user_id = authentication_service.authenticate()
        account_id = authentication_service.get_account_id()

        if self.public_access is False:
            verified = authentication_service.verify_access()
            if verified is False:
                raise exceptions.AuthenticationFailed("Sorry, you don't have access to the service.")

        access_groups = authentication_service.get_groups()
        quantum_user, created = User.objects.get_or_create(username=user_id)
        if created:
            logger.debug("New user [%s] created", user_id)
        if not UserAccessPolicies.can_access(quantum_user):
            raise exceptions.AuthenticationFailed(
                "Your user was deactivated. Please contact to IBM support for reactivaton."
            )

        if self.channel == Channel.LOCAL:
            permission_names = [VIEW_PROGRAM_PERMISSION, RUN_PROGRAM_PERMISSION]
            groups = self._restart_user_groups(
                user=quantum_user,
                authentication_groups=access_groups,
                permission_names=permission_names,
            )
            provider, created = Provider.objects.get_or_create(
                name="mockprovider",
                registry=settings.SETTINGS_AUTH_MOCKPROVIDER_REGISTRY,
            )
            if created:
                for admin_group in groups:
                    provider.admin_groups.add(admin_group)
        else:
            permission_names = [VIEW_PROGRAM_PERMISSION]
            self._restart_user_groups(
                user=quantum_user,
                authentication_groups=access_groups,
                permission_names=permission_names,
            )

        return quantum_user, account_id

    def _restart_user_groups(
        self,
        user: type[AbstractUser],
        authentication_groups: List[AuthenticationGroup],
        permission_names: List[str],
    ) -> List[Group]:
        new_groups = []

        permissions = []
        for permission_name in permission_names:
            permissions.append(Permission.objects.get(codename=permission_name))

        user.groups.clear()

        for authentication_group in authentication_groups:
            group, created = Group.objects.get_or_create(name=authentication_group.group_name)
            if created:
                for permission in permissions:
                    group.permissions.add(permission)
            if authentication_group.account is not None:
                GroupMetadata.objects.update_or_create(group=group, defaults={"account": authentication_group.account})
            group.user_set.add(user)
            new_groups.append(group)

        return new_groups
