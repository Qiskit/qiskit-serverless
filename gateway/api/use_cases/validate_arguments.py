"""Use case: validate job arguments against the function's JSON Schema."""

import json
import jsonschema


def validate_arguments(program, arguments_str: str) -> None:
    """Validate arguments_str against program.arguments_schema.

    No-op if schema is empty. Raises jsonschema.ValidationError if invalid.
    Raises json.JSONDecodeError if arguments_str is not valid JSON.
    """
    schema_str = program.arguments_schema
    if not schema_str or schema_str == "{}":
        return
    schema = json.loads(schema_str)
    if not schema:
        return
    arguments = json.loads(arguments_str or "{}")
    jsonschema.validate(instance=arguments, schema=schema)
