"""
Access policy functions for determining user permissions on functions.
"""
from enum import Enum, auto
from typing import Tuple, Optional

from django.contrib.auth.models import AbstractUser

from api.models import Program
from api.repositories.functions import FunctionRepository


class RunReason(Enum):
    """Reasons why a user cannot execute a function."""

    FUNCTION_DISABLED = auto()
    CONSENT_NOT_ACCEPTED = auto()


class FunctionAccessPolicy:
    """
    Policy class for functions.
    """

    function_repository = FunctionRepository()

    @staticmethod
    def can_run(
        user: AbstractUser, function: Program
    ) -> Tuple[bool, Optional[RunReason]]:
        """
        Determines if a user can run a specific function.

        Args:
            user: The user attempting to run the function
            function: The function (program) being attempted to run

        Returns:
            A tuple containing:
                - A boolean indicating if the user can run the function
                - Optionally, the reason why they cannot run it (if applicable)
        """
        if function.disabled:
            return False, RunReason.FUNCTION_DISABLED

        if user == function.author:
            return True, None

        log_consent = FunctionAccessPolicy.function_repository.get_log_consent(
            user, function
        )

        if not log_consent or not log_consent.accepted:
            return False, RunReason.CONSENT_NOT_ACCEPTED

        return True, None
