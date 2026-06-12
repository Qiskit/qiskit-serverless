import json
import jsonschema


def validate_arguments(program, arguments_str: str) -> None:
    schema_str = program.arguments_schema
    if not schema_str or schema_str == "{}":
        return
    schema = json.loads(schema_str)
    if not schema:
        return
    arguments = json.loads(arguments_str)
    jsonschema.validate(instance=arguments, schema=schema)
