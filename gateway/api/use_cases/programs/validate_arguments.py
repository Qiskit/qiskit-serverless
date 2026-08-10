"""Use case: validate job arguments against the function's JSON Schema."""

import json

import jsonschema
from django.contrib.auth.models import AbstractUser
from referencing.exceptions import Unresolvable

from api.access_policies.jobs import JobAccessPolicies
from api.domain.arguments_schema import (
    MAX_ARGUMENTS_LENGTH,
    MAX_DOCUMENT_DEPTH,
    UnsupportedSchemaError,
    check_arguments_schema,
    exceeds_max_depth,
    validate_at_bounded_cost,
)
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.domain.exceptions.invalid_arguments_exception import InvalidArgumentsException
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import (
    PLATFORM_PERMISSION_RUN,
    RUN_PROGRAM_PERMISSION,
    Program as Function,
)

# Longest validator message the API will hand back. jsonschema builds its messages with
# repr(instance), so without a limit a rejected 200 KB payload came back in full in the 400.
MAX_MESSAGE_LENGTH = 500


def _shortened(message: str) -> str:
    """Cut ``message`` down to something a client can read, keeping the informative front."""
    if len(message) <= MAX_MESSAGE_LENGTH:
        return message
    return f"{message[:MAX_MESSAGE_LENGTH]}... (message truncated)"


def validate_arguments(program: Function, arguments_str: str) -> None:
    """Validate arguments_str against program.arguments_schema.

    No-op if schema is empty. Raises InvalidArgumentsException if arguments_str is not
    valid JSON, if it does not match the schema, or if the schema itself cannot be used.
    """
    schema_str = program.arguments_schema
    if not schema_str or schema_str == "{}":
        return

    if len(arguments_str or "") > MAX_ARGUMENTS_LENGTH:
        raise InvalidArgumentsException(
            f"arguments are {len(arguments_str)} characters long and the maximum is {MAX_ARGUMENTS_LENGTH}"
        )

    try:
        schema = json.loads(schema_str)
    except json.JSONDecodeError as exc:
        raise InvalidArgumentsException(f"the function arguments schema is not valid JSON: {exc.msg}") from exc

    # Only the empty object means "no schema". "false" is the schema that rejects every instance,
    # so treating the parsed value as a boolean would turn the strictest schema into no validation.
    if isinstance(schema, dict) and not schema:
        return

    try:
        arguments = json.loads(arguments_str or "{}")
    except json.JSONDecodeError as exc:
        raise InvalidArgumentsException(f"arguments is not valid JSON: {exc.msg}") from exc

    if exceeds_max_depth(arguments):
        raise InvalidArgumentsException(f"arguments are nested more than {MAX_DOCUMENT_DEPTH} levels deep")

    try:
        check_arguments_schema(schema, schema_str)
        validate_at_bounded_cost(schema, arguments, schema_str)
    except RecursionError as exc:
        # A "$ref" back to the root of the document recurses forever in 13 characters, so depth
        # limits cannot catch every case and this is what keeps it from surfacing as a 500.
        raise InvalidArgumentsException("the function arguments schema recurses without end") from exc
    except UnsupportedSchemaError as exc:
        raise InvalidArgumentsException(_shortened(f"the function arguments schema cannot be used: {exc}")) from exc
    except jsonschema.SchemaError as exc:
        raise InvalidArgumentsException(
            _shortened(f"the function arguments schema is not usable: {exc.message}")
        ) from exc
    except jsonschema.ValidationError as exc:
        raise InvalidArgumentsException(_shortened(exc.message), path=list(exc.path)) from exc
    except Unresolvable as exc:
        raise InvalidArgumentsException(
            _shortened(f"the function arguments schema references something that cannot be resolved: {exc}")
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
