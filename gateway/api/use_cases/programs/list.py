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
        provider: str | None = None,
    ) -> list[Function]:
        """Return functions the user can see, filtered by type_filter and provider.

        When provider is given, results are narrowed to that provider's functions. The
        narrowing is applied after permission scoping, so it can only reduce the set the
        user is already allowed to see -- an unknown or inaccessible provider yields [].
        """
        if type_filter == TypeFilter.SERVERLESS:
            queryset = Function.objects.user_functions(user)
        elif type_filter == TypeFilter.CATALOG:
            queryset = Function.objects.provider_functions().with_permission(
                user,
                accessible_functions=accessible_functions,
                legacy_permission_name=RUN_PROGRAM_PERMISSION,
                permission=PLATFORM_PERMISSION_READ,
            )
        else:
            queryset = Function.objects.with_permission(
                user,
                accessible_functions=accessible_functions,
                legacy_permission_name=VIEW_PROGRAM_PERMISSION,
                permission=PLATFORM_PERMISSION_READ,
            )

        if provider:
            queryset = queryset.filter(provider__name=provider)

        return list(queryset)
