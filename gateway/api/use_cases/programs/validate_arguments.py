"""Use case: validate job arguments against the function's JSON Schema."""

import json

import jsonschema
from django.contrib.auth.models import AbstractUser
from referencing import Registry
from referencing.exceptions import Unresolvable

from api.access_policies.jobs import JobAccessPolicies
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.domain.exceptions.invalid_arguments_exception import InvalidArgumentsException
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import (
    PLATFORM_PERMISSION_RUN,
    RUN_PROGRAM_PERMISSION,
    Program as Function,
)

# An arguments schema is uploaded by whoever owns the function, so it is untrusted input that the
# gateway later evaluates. jsonschema resolves "$ref" by fetching the target, which would let a
# schema make the gateway issue arbitrary HTTP requests from inside the cluster or read local files.
# An empty registry has no retrieval hook, so an external reference resolves to nothing and raises
# Unresolvable instead. Internal references such as "#/$defs/name" still work: they are resolved
# against the schema document itself, not through the registry.
_NO_EXTERNAL_REFS = Registry()


def validate_arguments(program: Function, arguments_str: str) -> None:
    """Validate arguments_str against program.arguments_schema.

    No-op if schema is empty. Raises InvalidArgumentsException if arguments_str is not
    valid JSON, if it does not match the schema, or if the schema itself cannot be used.
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

    validator_class = jsonschema.validators.validator_for(schema)
    try:
        validator_class.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise InvalidArgumentsException(f"the function arguments schema is not usable: {exc.message}") from exc

    try:
        validator_class(schema, registry=_NO_EXTERNAL_REFS).validate(arguments)
    except jsonschema.ValidationError as exc:
        raise InvalidArgumentsException(exc.message, path=list(exc.path)) from exc
    except Unresolvable as exc:
        raise InvalidArgumentsException(
            f"the function arguments schema references something that cannot be resolved: {exc}"
        ) from exc


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
