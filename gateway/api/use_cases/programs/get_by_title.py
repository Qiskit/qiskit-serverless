"""Use case: retrieve a Qiskit Function by title."""

from django.contrib.auth.models import AbstractUser

from api.access_policies.programs import ProgramAccessPolicies
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Program as Function


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
            function = Function.objects.get_function(title, provider)
            if function is not None and not ProgramAccessPolicies.can_read(user, function, accessible_functions):
                function = None
        else:
            function = Function.objects.get_user_function(user, title)

        if function is None:
            raise FunctionNotFoundException(function=title, provider=provider)

        return function
