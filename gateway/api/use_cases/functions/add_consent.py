"""
Module for handling user consent for function logging operations.
"""

import logging
from django.contrib.auth.models import AbstractUser
from api.repositories.functions import FunctionRepository
from api.v1.endpoint_handle_exceptions import NotFoundError
from api.models import VIEW_PROGRAM_PERMISSION

logger = logging.getLogger("gateway.use_cases.functions")


class AddLogConsentUseCase:
    """
    Use case for managing user consent for function logging.
    """

    function_repository = FunctionRepository()

    def execute(
        self,
        user: AbstractUser,
        function_title: str,
        provider_name: str,
        accepted: bool,
    ):
        """
        Add log consent for a user to a specific function.

        Args:
            user (AbstractUser): The user giving consent
            function_title (str): The title of the function to give consent for
            accepted (bool): Whether consent is accepted or denied

        Raises:
            NotFoundError: If the function with the given title is not found
        """
        function = self.function_repository.get_provider_function_by_permission(
            author=user,
            permission_name=VIEW_PROGRAM_PERMISSION,
            title=function_title,
            provider_name=provider_name,
        )
        if function is None:
            raise NotFoundError(f"Function [{function_title}] not found")

        self.function_repository.add_log_consent_to_function(
            user=user, function=function, accepted=accepted
        )
