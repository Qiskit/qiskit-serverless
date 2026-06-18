"""Use case: list Qiskit Functions for a user."""

from django.contrib.auth.models import AbstractUser

from core.domain.authorization.function_access_result import FunctionAccessResult
from core.enums.type_filter import TypeFilter
from core.models import (
    PLATFORM_PERMISSION_READ,
    RUN_PROGRAM_PERMISSION,
    VIEW_PROGRAM_PERMISSION,
    Program as Function,
)


class ListFunctionsUseCase:
    """Use case for listing Qiskit Functions accessible to a user."""

    def execute(
        self,
        user: AbstractUser,
        accessible_functions: FunctionAccessResult,
        type_filter: str | None,
    ) -> list[Function]:
        """Return functions the user can see, filtered by type_filter."""
        if type_filter == TypeFilter.SERVERLESS:
            return list(Function.objects.user_functions(user))

        if type_filter == TypeFilter.CATALOG:
            return list(
                Function.objects.provider_functions().with_permission(
                    user,
                    accessible_functions=accessible_functions,
                    legacy_permission_name=RUN_PROGRAM_PERMISSION,
                    permission=PLATFORM_PERMISSION_READ,
                )
            )

        return list(
            Function.objects.with_permission(
                user,
                accessible_functions=accessible_functions,
                legacy_permission_name=VIEW_PROGRAM_PERMISSION,
                permission=PLATFORM_PERMISSION_READ,
            )
        )
