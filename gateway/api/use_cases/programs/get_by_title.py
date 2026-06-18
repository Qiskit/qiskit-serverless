"""Use case: retrieve a Qiskit Function by title."""

from django.contrib.auth.models import AbstractUser

from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import (
    PLATFORM_PERMISSION_READ,
    VIEW_PROGRAM_PERMISSION,
    Program as Function,
)


class GetFunctionByTitleUseCase:
    """Use case for retrieving a single Qiskit Function by title and optional provider."""

    def execute(
        self,
        user: AbstractUser,
        accessible_functions: FunctionAccessResult,
        title: str,
        provider: str | None,
    ) -> Function:
        """Return the function if found and accessible, else raise FunctionNotFoundException.

        Both "not found" and "no access" raise the same exception to avoid
        leaking information about function existence.
        """
        if provider:
            function = Function.objects.get_function_by_permission(
                user=user,
                function_title=title,
                provider_name=provider,
                accessible_functions=accessible_functions,
                permission=PLATFORM_PERMISSION_READ,
                legacy_permission_name=VIEW_PROGRAM_PERMISSION,
            )
        else:
            function = Function.objects.get_user_function(user, title)

        if function is None:
            raise FunctionNotFoundException(function=title, provider=provider)

        return function
