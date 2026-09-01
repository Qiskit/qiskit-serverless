"""Use case: retrieve a Qiskit Function's declared size catalog and default size."""

from django.contrib.auth.models import AbstractUser

from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import (
    FunctionSize,
    PLATFORM_PERMISSION_READ,
    VIEW_PROGRAM_PERMISSION,
    Program as Function,
)


class GetFunctionSizesUseCase:
    """Use case for retrieving a function's size catalog and default size.

    Resolves the function with the same access rules as reading it by title, so
    the sizes are only exposed to a user who can view the function.
    """

    def execute(
        self,
        user: AbstractUser,
        accessible_functions: FunctionAccessResult,
        title: str,
        provider: str | None,
    ) -> tuple[list[FunctionSize], FunctionSize | None]:
        """Return ``(size rows, default size row)`` for an accessible function.

        Both "not found" and "no access" raise the same exception to avoid
        leaking information about function existence, matching
        :class:`GetFunctionByTitleUseCase`.
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

        sizes = list(FunctionSize.objects.function_sizes(function).select_related("compute_profile"))
        return sizes, function.default_size
