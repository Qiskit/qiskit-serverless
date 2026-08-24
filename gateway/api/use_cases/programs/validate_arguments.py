"""Use case: validate job arguments against the function's JSON Schema."""

import json

import jsonschema
from django.contrib.auth.models import AbstractUser

from api.access_policies.jobs import JobAccessPolicies
from api.domain.arguments_schema import (
    MAX_DOCUMENT_DEPTH,
    MAX_SCHEMA_LENGTH,
    MAX_SCHEMA_NODES,
    InvalidArgumentsError,
    UnsupportedSchemaError,
    exceeds_max_depth,
    exceeds_max_nodes,
    max_arguments_length,
    validate_arguments_in_isolation,
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


def _shortened_path(path: list) -> list:
    """Truncate any string segment of a validation path the same way _shortened truncates message.

    A property name is as caller-controlled as the message text next to it: an
    ``additionalProperties`` schema against a 900 000 character property name put that property
    name straight into the path, in full, while the message beside it was already capped. Array
    indices are ints, not strings, and are left alone.
    """
    return [_shortened(segment) if isinstance(segment, str) else segment for segment in path]


def validate_arguments(program: Function, arguments_str: str) -> None:
    """Validate arguments_str against program.arguments_schema.

    No-op if the schema is empty. The cheap text limits run here; everything that evaluates the
    schema runs in a child with hard limits, so a pathological schema costs a bounded amount and
    comes back as a rejection rather than a 500 or an occupied worker.

    Raises:
        InvalidArgumentsException: if the arguments do not match the schema, are not valid JSON,
            exceed a limit, or the stored schema cannot be used.
    """
    schema_str = program.arguments_schema
    if not schema_str or schema_str == "{}":
        return

    if len(schema_str) > MAX_SCHEMA_LENGTH:
        raise InvalidArgumentsException(
            f"the function arguments schema is {len(schema_str)} characters long "
            f"and the maximum is {MAX_SCHEMA_LENGTH}"
        )

    maximum_arguments = max_arguments_length()
    if len(arguments_str or "") > maximum_arguments:
        raise InvalidArgumentsException(
            f"arguments are {len(arguments_str)} characters long and the maximum is {maximum_arguments}"
        )

    try:
        schema = json.loads(schema_str)
    except (json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise InvalidArgumentsException("the function arguments schema is not valid JSON") from exc

    # Only the empty object means "no schema". "false" is the schema that rejects every instance,
    # so treating the parsed value as a boolean would turn the strictest schema into no validation.
    if isinstance(schema, dict) and not schema:
        return

    if exceeds_max_depth(schema):
        raise InvalidArgumentsException(
            f"the function arguments schema is nested more than {MAX_DOCUMENT_DEPTH} levels deep"
        )

    if exceeds_max_nodes(schema):
        raise InvalidArgumentsException(
            f"the function arguments schema contains more than {MAX_SCHEMA_NODES} subschemas"
        )

    try:
        validate_arguments_in_isolation(schema, arguments_str or "{}")
    except InvalidArgumentsError as exc:
        # The caller's own mistake, not the schema's: report it as-is, without the schema prefix
        # below, so a malformed request does not read as the function owner's schema being broken.
        raise InvalidArgumentsException(_shortened(str(exc))) from exc
    except UnsupportedSchemaError as exc:
        raise InvalidArgumentsException(_shortened(f"the function arguments schema cannot be used: {exc}")) from exc
    except jsonschema.ValidationError as exc:
        raise InvalidArgumentsException(_shortened(exc.message), path=_shortened_path(list(exc.path))) from exc


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
