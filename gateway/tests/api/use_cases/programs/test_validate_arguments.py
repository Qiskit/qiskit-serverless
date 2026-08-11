"""Unit tests for validate_arguments and ValidateArgumentsUseCase."""

import json
import time
import jsonschema
import pytest
from unittest.mock import MagicMock
from django.contrib.auth.models import User

from api.domain import arguments_schema as arguments_schema_module
from api.domain.arguments_schema import (
    MAX_ARGUMENTS_LENGTH,
    MAX_SCHEMA_LENGTH,
    MAX_SCHEMA_NODES,
    UnsupportedSchemaError,
    check_uploaded_schema_in_isolation,
    exceeds_max_nodes,
    validate_arguments_in_isolation,
)
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.domain.exceptions.invalid_arguments_exception import InvalidArgumentsException
from api.use_cases.programs.validate_arguments import ValidateArgumentsUseCase, validate_arguments
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Program


def _program(schema_dict):
    p = MagicMock()
    p.arguments_schema = json.dumps(schema_dict)
    return p


def _refused_within(seconds, schema, arguments_str):
    """Assert the schema is refused, and quickly. Returns how long it took."""
    start = time.monotonic()
    with pytest.raises(UnsupportedSchemaError):
        validate_arguments_in_isolation(schema, arguments_str)
    elapsed = time.monotonic() - start
    assert elapsed < seconds, f"took {elapsed:.2f}s"
    return elapsed


def test_root_dollar_schema_no_longer_restores_the_backtracking_engine():
    """Measured at 0.4907s for 24 characters before, doubling per character: 40 is hours."""
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "pattern": "^(a+)+$",
        "properties": {"x": {"$ref": "#"}},
    }
    _refused_within(4.0, schema, json.dumps({"x": "a" * 40 + "!"}))


def test_a_large_regex_program_cannot_run_for_minutes():
    """A 6189 byte pattern matched against 24000 characters is comfortably past the 1 CPU-second
    budget on this hardware (measured at 0.61s for 8000, 1.92s for 24000). Assert the time is
    bounded rather than a specific exception: on faster hardware the match finishes inside the
    budget and raises jsonschema.ValidationError instead of UnsupportedSchemaError, the same way
    the uniqueItems timing test below does not assert which of the two happened."""
    pattern = "(?:" + "|".join(f"a{{{i}}}" for i in range(1, 900)) + ")b"
    schema = {"type": "object", "properties": {"x": {"type": "string", "pattern": pattern}}}
    start = time.monotonic()
    try:
        validate_arguments_in_isolation(schema, json.dumps({"x": "a" * 24000}))
    except (UnsupportedSchemaError, jsonschema.ValidationError):
        pass
    assert time.monotonic() - start < 4.0


def test_a_reference_to_the_root_is_reported_not_a_crash():
    """13 characters that recurse forever. It used to reach the generic handler as a 500."""
    with pytest.raises(UnsupportedSchemaError):
        validate_arguments_in_isolation({"$ref": "#"}, "{}")


def test_unique_items_on_a_large_array_of_objects_is_bounded():
    """8000 objects took 32.2s with the stock keyword."""
    items = json.dumps([{"i": i} for i in range(8000)])
    start = time.monotonic()
    try:
        validate_arguments_in_isolation({"type": "array", "uniqueItems": True}, items)
    except UnsupportedSchemaError:
        pass
    assert time.monotonic() - start < 4.0


def test_an_ordinary_schema_still_accepts_and_rejects_the_same_values():
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string", "pattern": "^ibm_[a-z0-9_]+$"}},
        "required": ["name"],
    }
    validate_arguments_in_isolation(schema, json.dumps({"name": "ibm_backend_1"}))
    with pytest.raises(jsonschema.ValidationError):
        validate_arguments_in_isolation(schema, json.dumps({"name": "NOPE"}))
    with pytest.raises(jsonschema.ValidationError):
        validate_arguments_in_isolation(schema, "{}")


def test_internal_references_still_resolve():
    schema = {
        "$defs": {"shots": {"type": "integer", "minimum": 1}},
        "type": "object",
        "properties": {"shots": {"$ref": "#/$defs/shots"}},
    }
    validate_arguments_in_isolation(schema, json.dumps({"shots": 1024}))
    with pytest.raises(jsonschema.ValidationError):
        validate_arguments_in_isolation(schema, json.dumps({"shots": 0}))


def test_boolean_schemas_keep_their_meaning():
    validate_arguments_in_isolation(True, json.dumps({"anything": 1}))
    with pytest.raises(jsonschema.ValidationError):
        validate_arguments_in_isolation(False, json.dumps({"anything": 1}))


def test_a_declared_format_is_still_asserted():
    with pytest.raises(jsonschema.ValidationError):
        validate_arguments_in_isolation({"type": "string", "format": "email"}, '"not-an-email"')


def test_the_validation_error_keeps_its_path():
    schema = {
        "properties": {
            "outer": {"properties": {"inner": {"type": "integer"}}},
            "circuits": {"type": "array", "items": {"type": "integer"}},
        }
    }
    with pytest.raises(jsonschema.ValidationError) as caught:
        validate_arguments_in_isolation(schema, json.dumps({"outer": {"inner": "no"}}))
    assert list(caught.value.path) == ["outer", "inner"]

    # An array index must stay an int, not become the string "1": jsonschema's own path does, and
    # stringifying it here would change the API contract for no benefit.
    with pytest.raises(jsonschema.ValidationError) as caught:
        validate_arguments_in_isolation(schema, json.dumps({"circuits": [1, "no"]}))
    assert list(caught.value.path) == ["circuits", 1]


def test_uniqueitems_still_rejects_a_duplicate():
    """The hash-based uniqueItems replacement is back, so confirm it still does its job and not only that it is fast."""
    with pytest.raises(jsonschema.ValidationError):
        validate_arguments_in_isolation({"type": "array", "uniqueItems": True}, '[{"a":1},{"a":1}]')


def test_deeply_nested_arguments_are_rejected_not_a_crash():
    """3000 levels in 18 KB raised RecursionError inside json.loads, before the protected block."""
    with pytest.raises(InvalidArgumentsException):
        validate_arguments(_program({"type": "object"}), '{"a":' * 3000 + "1" + "}" * 3000)


def test_an_enormous_number_in_the_arguments_is_rejected_not_a_crash():
    """json.loads raises ValueError above 4300 digits, and only JSONDecodeError was caught."""
    with pytest.raises(InvalidArgumentsException):
        validate_arguments(_program({"type": "object"}), '{"a": ' + "9" * 4301 + "}")


def test_a_schema_with_too_many_nodes_is_rejected():
    """anyOf of 2000 branches against 500 KB reached 1.55 GB of RSS."""
    program = _program({"anyOf": [{"type": "integer"}] * (MAX_SCHEMA_NODES + 1)})
    with pytest.raises(InvalidArgumentsException) as caught:
        validate_arguments(program, "7")
    assert "subschemas" in caught.value.message


def test_empty_schema_always_passes():
    program = MagicMock()
    program.arguments_schema = "{}"
    validate_arguments(program, '{"anything": "goes"}')  # must not raise


def test_valid_arguments_pass():
    schema = {"type": "object", "required": ["shots"], "properties": {"shots": {"type": "integer"}}}
    validate_arguments(_program(schema), '{"shots": 1024}')  # must not raise


def test_invalid_arguments_raise():
    schema = {"type": "object", "required": ["shots"], "properties": {"shots": {"type": "integer"}}}
    with pytest.raises(InvalidArgumentsException):
        validate_arguments(_program(schema), '{"shots": "not-an-int"}')


def test_missing_required_field_raises():
    schema = {"type": "object", "required": ["shots"]}
    with pytest.raises(InvalidArgumentsException):
        validate_arguments(_program(schema), "{}")


def test_invalid_json_raises_invalid_arguments_exception():
    """The message must read as the caller's own mistake, not as the function's schema being
    broken: no "the function arguments schema" prefix, matching what specs/ARGUMENTS_VALIDATION.md
    documents for this case."""
    schema = {"type": "object", "required": ["shots"]}
    with pytest.raises(InvalidArgumentsException, match="^arguments is not valid JSON"):
        validate_arguments(_program(schema), "not-valid-json{{{")


def test_oversized_schema_is_rejected():
    """A schema large enough to spell out a costly combination of subschemas is refused."""
    schema = {"type": "object", "description": "x" * (MAX_SCHEMA_LENGTH + 1)}
    with pytest.raises(InvalidArgumentsException, match="maximum"):
        validate_arguments(_program(schema), "{}")


def test_legitimate_pattern_still_validates():
    """An ordinary pattern keeps working, accepting and rejecting the same values as before."""
    schema = {"type": "object", "properties": {"backend": {"type": "string", "pattern": "^ibm_[a-z0-9_]+$"}}}

    validate_arguments(_program(schema), '{"backend": "ibm_torino"}')  # must not raise

    with pytest.raises(InvalidArgumentsException):
        validate_arguments(_program(schema), '{"backend": "not a backend"}')


def test_an_external_reference_is_not_fetched():
    """Asserts on sockets, not on the exception type: Unresolvable is raised either way, and with
    jsonschema's default registry it arrives after a real request. The previous version of this
    test passed while taking 75 seconds to time out against 169.254.169.254.

    validate_arguments_in_isolation always forks, and a fork's copy of a Python list is private to
    it: a spy that appends to one in the parent would stay looking empty no matter what the child
    did. A plain file predates the fork, so a write to it from the child is visible here.
    """
    import socket
    import tempfile

    real_getaddrinfo = socket.getaddrinfo

    with tempfile.TemporaryFile() as marker:

        def spy(*args, **kwargs):
            marker.write(repr(args[0]).encode() + b"\n")
            marker.flush()
            return real_getaddrinfo(*args, **kwargs)

        socket.getaddrinfo = spy
        try:
            with pytest.raises(UnsupportedSchemaError):
                validate_arguments_in_isolation({"$ref": "https://example.invalid/schema.json"}, "{}")
        finally:
            socket.getaddrinfo = real_getaddrinfo

        marker.seek(0)
        assert marker.read() == b""


def test_internal_ref_still_resolves():
    """Blocking external references must not break same-document ones."""
    schema = {
        "type": "object",
        "properties": {"shots": {"$ref": "#/$defs/positive"}},
        "$defs": {"positive": {"type": "integer", "minimum": 1}},
    }
    validate_arguments(_program(schema), '{"shots": 1024}')  # must not raise

    with pytest.raises(InvalidArgumentsException):
        validate_arguments(_program(schema), '{"shots": -5}')


def test_unusable_schema_is_reported_as_invalid_arguments_not_a_crash():
    """A stored schema that is not a valid JSON Schema must not surface as a 500.

    "integar" is not a recognised JSON Schema type, so jsonschema raises UnknownType while
    validating rather than a SchemaError, and the child reports it as an unusable schema.
    """
    with pytest.raises(InvalidArgumentsException, match="cannot be used"):
        validate_arguments(_program({"type": "integar"}), '{"shots": 1024}')


def test_arguments_longer_than_the_limit_are_rejected():
    """The work a validation does grows with the caller's payload, so its length is capped.

    Without a cap the ceiling is DATA_UPLOAD_MAX_MEMORY_SIZE, 2.5 MB by default, which is three
    orders of magnitude more input than any keyword was measured against.
    """
    arguments = json.dumps({"blob": "x" * (MAX_ARGUMENTS_LENGTH + 1)})

    with pytest.raises(InvalidArgumentsException, match="maximum"):
        validate_arguments(_program({"type": "object"}), arguments)


def test_unique_items_on_a_large_array_of_objects_stays_cheap():
    """'uniqueItems' compares values pairwise when they are not orderable, which is quadratic, and
    jsonschema's own implementation does exactly that: 4000 objects took about 8s that way, which
    the 1 CPU-second isolation budget would refuse outright. This is the case the hash-based
    _unique_items replacement exists to keep working: with it, the same 4000 objects answer in
    about 0.007s, comfortably inside the budget even with coverage instrumentation slowing the
    child down.
    """
    arguments = json.dumps([{"i": i} for i in range(4000)])
    start = time.perf_counter()

    validate_arguments(_program({"type": "array", "uniqueItems": True}), arguments)  # must not raise

    assert time.perf_counter() - start < 2


def test_unique_items_still_catches_a_duplicate():
    """Replacing the keyword must not turn it into a keyword that accepts everything."""
    with pytest.raises(InvalidArgumentsException):
        validate_arguments(_program({"type": "array", "uniqueItems": True}), '[{"i": 1}, {"i": 1}]')


def test_schema_false_rejects_everything_instead_of_disabling_validation():
    """'false' is the JSON Schema that rejects every instance, and it must not read as "no schema".

    Treating the parsed schema as a boolean turned the strictest schema there is into no validation
    at all, which is the wrong direction to fail in.
    """
    program = MagicMock()
    program.arguments_schema = "false"

    with pytest.raises(InvalidArgumentsException):
        validate_arguments(program, '{"anything": 1}')


def test_schema_true_still_accepts_everything():
    """'true' is the other boolean schema and it does accept every instance."""
    program = MagicMock()
    program.arguments_schema = "true"

    validate_arguments(program, '{"anything": 1}')  # must not raise


def test_scalar_schema_is_reported_instead_of_crashing():
    """A stored schema that is a JSON number reaches validator_for, which assumes a dict.

    '"$schema" not in schema' raises TypeError on a scalar, and nothing on the way here rejects it,
    so the request came out as a 500.
    """
    program = MagicMock()
    program.arguments_schema = "123"

    with pytest.raises(InvalidArgumentsException, match="object or a boolean"):
        validate_arguments(program, "{}")


def test_self_referencing_schema_is_reported_instead_of_crashing():
    """A '$ref' to the document root recurses forever in 13 bytes.

    RecursionError is not a subclass of anything the use case catches, so it fell through to the
    generic handler and came out as a 500.
    """
    with pytest.raises(InvalidArgumentsException):
        validate_arguments(_program({"$ref": "#"}), "{}")


def test_deeply_nested_schema_is_rejected():
    """Nesting alone reaches RecursionError, at a depth of about 180, in a few kilobytes."""
    schema: dict = {"not": {}}
    node = schema
    for _ in range(400):
        node["not"] = {"not": {}}
        node = node["not"]

    with pytest.raises(InvalidArgumentsException, match="nested"):
        validate_arguments(_program(schema), "1")


def test_deeply_nested_arguments_are_rejected():
    """The trigger can be the caller's payload against a schema that is perfectly ordinary.

    A recursive schema is the documented way to describe a tree, so the depth has to be capped on
    the instance as well, not just on the schema.
    """
    schema = {
        "$defs": {"node": {"type": "object", "properties": {"child": {"$ref": "#/$defs/node"}}}},
        "$ref": "#/$defs/node",
    }
    arguments: dict = {}
    node = arguments
    for _ in range(300):
        node["child"] = {}
        node = node["child"]

    with pytest.raises(InvalidArgumentsException, match="nested"):
        validate_arguments(_program(schema), json.dumps(arguments))


def test_declared_format_is_applied():
    """'format' is an annotation unless a checker is attached, so it used to reject nothing.

    A vendor writing 'format' got neither validation nor a warning that it does nothing.
    """
    schema = {"type": "object", "properties": {"contact": {"type": "string", "format": "email"}}}

    validate_arguments(_program(schema), '{"contact": "someone@example.com"}')  # must not raise

    with pytest.raises(InvalidArgumentsException):
        validate_arguments(_program(schema), '{"contact": "not-an-email"}')


def test_regex_format_is_not_asserted():
    """Asserting 'format: regex' would compile caller input with Python's backtracking engine.

    That is exactly the cost the isolation exists to bound, not something to trigger deliberately
    on every request that happens to declare this format, so it stays unchecked.
    """
    schema = {"type": "object", "properties": {"p": {"type": "string", "format": "regex"}}}

    validate_arguments(_program(schema), '{"p": "^(a+)+$"}')  # must not raise
    validate_arguments(_program(schema), '{"p": "unparseable("}')  # must not raise


def test_error_message_does_not_echo_the_whole_payload():
    """jsonschema builds its messages with repr(instance), so the 400 carried the input back.

    Measured: a 200 KB payload produced a 200 027 character message.
    """
    schema = {"type": "object", "properties": {"blob": {"type": "integer"}}}
    arguments = json.dumps({"blob": "x" * 50_000})

    with pytest.raises(InvalidArgumentsException) as caught:
        validate_arguments(_program(schema), arguments)

    assert len(caught.value.message) < 1000


def test_validation_error_path_does_not_echo_the_whole_property_name():
    """path carries data as caller-controlled as the message next to it, and used to go out
    untruncated: a 900 000 character property name produced a 28 character message next to a
    900 000 character path[0], in full, in the 400 body.
    """
    schema = {"additionalProperties": {"type": "integer"}}
    arguments = json.dumps({"x" * 900_000: "not-an-int"})

    with pytest.raises(InvalidArgumentsException) as caught:
        validate_arguments(_program(schema), arguments)

    assert len(caught.value.path[0]) < 1000


def test_validation_error_path_keeps_an_array_index_as_an_int_after_shortening():
    """Shortening the path must only touch string segments: an array index is caller-controlled
    too, but it is an int, and turning it into a truncated string would change the API contract for
    no benefit.
    """
    schema = {"properties": {"circuits": {"type": "array", "items": {"type": "integer"}}}}

    with pytest.raises(InvalidArgumentsException) as caught:
        validate_arguments(_program(schema), json.dumps({"circuits": [1, "no"]}))

    assert caught.value.path == ["circuits", 1]


def test_memory_limit_reason_is_named_through_the_real_validate_entry_point(monkeypatch):
    """arguments_schema.work() for validate_arguments_in_isolation used to have its own
    except Exception, which caught MemoryError before isolated.py's own handler could name the
    limit that fired: a real 400 read "the function arguments schema cannot be used: MemoryError:",
    with nothing after the colon, instead of naming the limit. Patching what validate() does, rather
    than actually allocating hundreds of MB, keeps this deterministic on every platform, including
    macOS where RLIMIT_AS never fires.
    """

    class _OutOfMemoryValidator:
        def validate(self, _instance):
            raise MemoryError

    monkeypatch.setattr(arguments_schema_module, "_validator", lambda schema: _OutOfMemoryValidator())

    with pytest.raises(UnsupportedSchemaError, match="memory"):
        validate_arguments_in_isolation({"type": "object"}, "{}")


def test_memory_limit_reason_is_named_through_the_real_upload_entry_point(monkeypatch):
    """Same bug, other real entry point: check_uploaded_schema_in_isolation's work() has the same
    shape and the same fix."""

    class _OutOfMemoryValidator:
        @staticmethod
        def check_schema(_schema):
            raise MemoryError

    monkeypatch.setattr(jsonschema.validators, "validator_for", lambda schema: _OutOfMemoryValidator)

    with pytest.raises(UnsupportedSchemaError, match="memory"):
        check_uploaded_schema_in_isolation("{}")


def test_node_count_refuses_a_wide_combination_and_allows_an_ordinary_schema():
    ordinary = {"type": "object", "properties": {"shots": {"type": "integer"}, "name": {"type": "string"}}}
    assert exceeds_max_nodes(ordinary) is False
    assert exceeds_max_nodes({"anyOf": [{"type": "integer"}] * (MAX_SCHEMA_NODES + 1)}) is True


def test_node_count_refuses_many_boolean_branches_under_length_limit():
    """A schema of many boolean branches under MAX_SCHEMA_LENGTH must still be refused.

    The bypass: {"anyOf": [False] * 8000} is 56011 bytes, under the 64 KB limit,
    but each False is a valid JSON Schema that produces a validation error with
    repr(instance) embedded, so memory use still scales with branches.
    """
    schema = {"anyOf": [False] * (MAX_SCHEMA_NODES + 1)}
    assert len(json.dumps(schema)) < MAX_SCHEMA_LENGTH
    assert exceeds_max_nodes(schema) is True


@pytest.mark.django_db
class TestValidateArgumentsUseCase:
    @pytest.fixture
    def user(self):
        return User.objects.create_user(username="author")

    def test_validates_own_function_arguments(self, user):
        schema = json.dumps({"type": "object", "required": ["shots"]})
        Program.objects.create(title="my-fn", author=user, entrypoint="main.py", arguments_schema=schema)
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        ValidateArgumentsUseCase().execute(user, accessible, "my-fn", None, '{"shots": 1024}')  # must not raise

    def test_raises_invalid_arguments_when_schema_violated(self, user):
        schema = json.dumps({"type": "object", "required": ["shots"]})
        Program.objects.create(title="my-fn", author=user, entrypoint="main.py", arguments_schema=schema)
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        with pytest.raises(InvalidArgumentsException):
            ValidateArgumentsUseCase().execute(user, accessible, "my-fn", None, "{}")

    def test_raises_not_found_when_function_does_not_exist(self, user):
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        with pytest.raises(FunctionNotFoundException):
            ValidateArgumentsUseCase().execute(user, accessible, "nonexistent-fn", None, "{}")

    def test_raises_not_found_when_no_permission_for_custom_function(self, user):
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        with pytest.raises(FunctionNotFoundException):
            ValidateArgumentsUseCase().execute(user, accessible, "my-fn", None, "{}")
