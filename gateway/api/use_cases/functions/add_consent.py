"""
Module for handling user consent for function logging operations.
"""

import logging
from django.contrib.auth.models import AbstractUser
from api.repositories.functions import FunctionRepository
from api.v1.endpoint_handle_exceptions import NotFoundError

logger = logging.getLogger("gateway.use_cases.functions")


class AddLogConsentUseCase:
    """
    Use case for managing user consent for function logging.
    """

    function_repository = FunctionRepository()

    def execute(self, user: AbstractUser, function_title: str, accepted: bool):
        """
        Add log consent for a user to a specific function.

        Args:
            user (AbstractUser): The user giving consent
            function_title (str): The title of the function to give consent for
            accepted (bool): Whether consent is accepted or denied

        Raises:
            NotFoundError: If the function with the given title is not found
        """
        function = self.function_repository.get_function_by_permission(
            user=user,
            permission_name="RUN_PROGRAM_PERMISSION",
            function_title=function_title,
        )
        if function is None:
            raise NotFoundError(f"Function [{function_title}] not found")

        self.function_repository.add_log_consent_to_function(
            user=user, function=function, accepted=accepted
        )
