"""Use case: validate job arguments against the function's JSON Schema."""

import json

import jsonschema
from django.contrib.auth.models import AbstractUser

from api.access_policies.jobs import JobAccessPolicies
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.domain.exceptions.invalid_arguments_exception import InvalidArgumentsException
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import (
    PLATFORM_PERMISSION_RUN,
    RUN_PROGRAM_PERMISSION,
    Program as Function,
)


def validate_arguments(program: Function, arguments_str: str) -> None:
    """Validate arguments_str against program.arguments_schema.

    No-op if schema is empty. Raises InvalidArgumentsException if arguments_str is not
    valid JSON or does not match the schema.
    """
    schema_str = program.arguments_schema
    if not schema_str or schema_str == "{}":
        return
    schema = json.loads(schema_str)
    if not schema:
        return
    try:
        arguments = json.loads(arguments_str or "{}")
    except json.JSONDecodeError as exc:
        raise InvalidArgumentsException(f"arguments is not valid JSON: {exc.msg}") from exc
    try:
        jsonschema.validate(instance=arguments, schema=schema)
    except jsonschema.ValidationError as exc:
        raise InvalidArgumentsException(exc.message, path=list(exc.path)) from exc


class ValidateArgumentsUseCase:
    """Use case for validating job arguments against a Qiskit Function's schema."""

    def execute(
        self,
        user: AbstractUser,
        accessible_functions: FunctionAccessResult,
        title: str,
        provider_name: str | None,
        arguments: str,
    ) -> None:
        """Validate arguments against the named function's schema without creating a job.

        Raises FunctionNotFoundException when the function doesn't exist or isn't accessible.
        Raises InvalidArgumentsException when the arguments are invalid JSON or don't match the schema.
        """
        function = None
        if provider_name:
            function = Function.objects.get_function_by_permission(
                user=user,
                function_title=title,
                provider_name=provider_name,
                accessible_functions=accessible_functions,
                permission=PLATFORM_PERMISSION_RUN,
                legacy_permission_name=RUN_PROGRAM_PERMISSION,
            )
        else:
            if JobAccessPolicies.can_create(user=user, accessible_functions=accessible_functions):
                function = Function.objects.get_user_function(user, title)

        if function is None:
            raise FunctionNotFoundException(function=title, provider=provider_name)

        validate_arguments(function, arguments)
