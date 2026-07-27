"""Use case: validate job arguments against the function's JSON Schema."""

import json
import jsonschema

from api.domain.exceptions.invalid_arguments_exception import InvalidArgumentsException


def validate_arguments(program, arguments_str: str) -> None:
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
