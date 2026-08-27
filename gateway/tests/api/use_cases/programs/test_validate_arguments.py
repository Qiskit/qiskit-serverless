"""Unit tests for validate_arguments and ValidateArgumentsUseCase."""

import json
import time
import jsonschema
import pytest
from unittest.mock import MagicMock
from django.conf import settings
from django.contrib.auth.models import User

from api.domain import arguments_schema as arguments_schema_module
from api.domain.arguments_schema import (
    MAX_SCHEMA_LENGTH,
    MAX_SCHEMA_NODES,
    UnsupportedSchemaError,
    check_uploaded_schema_in_isolation,
    exceeds_max_nodes,
    validate_arguments_in_isolation,
)
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.domain.exceptions.invalid_arguments_exception import InvalidArgumentsException
from api.use_cases.programs.validate_arguments import MAX_MESSAGE_LENGTH, ValidateArgumentsUseCase, validate_arguments
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Program


def _program(schema_dict):
    p = MagicMock()
    p.arguments_schema = json.dumps(schema_dict)
    return p


def test_root_dollar_schema_no_longer_restores_the_backtracking_engine():
    """{"$ref": "#"} pointing back at a schema with its own "pattern" used to hand the caller's
    string straight to Python's backtracking regex engine on every property that referenced it:
    measured at 0.4907s for 24 characters before, doubling per character, so 40 is hours.

    Assert the cause in the message rather than elapsed wall-clock time: RLIMIT_CPU firing (the
    "CPU time" reason) is what proves the backtracking engine got cut off, independent of how
    long that takes on a loaded or CPU-throttled runner. The wall-clock fallback path reports a
    different reason ("wall-clock time"), so this alone rules out the fallback satisfying the
    test by accident.
    """
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "pattern": "^(a+)+$",
        "properties": {"x": {"$ref": "#"}},
    }
    with pytest.raises(UnsupportedSchemaError) as caught:
        validate_arguments_in_isolation(schema, json.dumps({"x": "a" * 40 + "!"}))
    assert "CPU time" in str(caught.value)


def test_a_large_regex_program_cannot_run_for_minutes():
    """A 6189 byte pattern matched against 24000 characters is comfortably past the 1 CPU-second
    budget on this hardware (measured at 0.61s for 8000, 1.92s for 24000). Assert the time is
    bounded rather than a specific exception: on faster hardware the match finishes inside the
    budget and raises jsonschema.ValidationError instead of UnsupportedSchemaError, the same way
    the uniqueItems timing test below does not assert which of the two happened.

    The bound below is deliberately loose and is not a performance assertion: run_isolated's own
    wall-clock fallback (wall_seconds, five times the CPU budget, so 5.0s at the default budget of
    one second) is a hard ceiling on how long the forked child can run at all, regardless of CPU
    speed or throttling, so the real worst case here is
    that fallback plus fork/pipe/teardown overhead, not how much work the child got done. 30s
    leaves several times that margin for a loaded or CPU-throttled runner, while still catching
    the actual bug this test guards against: a schema that runs for minutes.
    """
    pattern = "(?:" + "|".join(f"a{{{i}}}" for i in range(1, 900)) + ")b"
    schema = {"type": "object", "properties": {"x": {"type": "string", "pattern": pattern}}}
    start = time.monotonic()
    try:
        validate_arguments_in_isolation(schema, json.dumps({"x": "a" * 24000}))
    except (UnsupportedSchemaError, jsonschema.ValidationError):
        pass
    assert time.monotonic() - start < 30.0


def test_a_reference_to_the_root_is_reported_not_a_crash():
    """13 characters that recurse forever. It used to reach the generic handler as a 500."""
    with pytest.raises(UnsupportedSchemaError):
        validate_arguments_in_isolation({"$ref": "#"}, "{}")


def test_unique_items_on_a_large_array_of_objects_is_bounded():
    """8000 objects took 32.2s with the stock keyword.

    Same loose, non-performance bound as test_a_large_regex_program_cannot_run_for_minutes above,
    for the same reason: run_isolated's own wall_seconds fallback (five times the CPU budget, so
    5.0s at the default budget) is the real ceiling on the child, so 30s leaves ample margin for a
    loaded or CPU-throttled runner while still catching an actual runaway.
    """
    items = json.dumps([{"i": i} for i in range(8000)])
    start = time.monotonic()
    try:
        validate_arguments_in_isolation({"type": "array", "uniqueItems": True}, items)
    except UnsupportedSchemaError:
        pass
    assert time.monotonic() - start < 30.0


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
    """3000 levels in 18 KB used to reach json.loads outside the protected block and crash.

    As with the upload path, which mechanism refuses them is left to the interpreter: json.loads
    gives up at this depth on Python 3.11, while on 3.12 it parses and MAX_DOCUMENT_DEPTH answers.
    Either way the caller gets InvalidArgumentsException rather than a crash, which is the point.
    """
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


def test_check_uploaded_schema_rejects_self_referencing_root_schema():
    """{"$ref": "#"} passes the metaschema check and then recurses forever on every future run:
    the metaschema check only verifies the document is a valid JSON Schema, it never evaluates it.
    The trial validation this module now runs at upload catches it there instead.
    """
    with pytest.raises(UnsupportedSchemaError, match="RecursionError"):
        check_uploaded_schema_in_isolation(json.dumps({"$ref": "#"}))


def test_check_uploaded_schema_rejects_an_unresolvable_ref_nested_in_properties():
    """A broken reference under "properties" is never touched by a trial validation against an
    empty instance: jsonschema does not descend into a property the instance does not have.
    Measured: the same broken reference raises when placed at the schema's root and raises
    nothing when moved under "properties.x". The document walk this module also runs at upload
    catches it regardless of where it sits.
    """
    schema = {"type": "object", "properties": {"x": {"$ref": "#/$defs/nope"}}}
    with pytest.raises(UnsupportedSchemaError, match="does not resolve: '#/\\$defs/nope'"):
        check_uploaded_schema_in_isolation(json.dumps(schema))


def test_check_uploaded_schema_rejects_an_unresolvable_ref_nested_in_items():
    """Same gap as the properties case, for "items": an empty instance is not a non-empty array,
    so jsonschema never evaluates against it either."""
    schema = {"type": "object", "properties": {"xs": {"type": "array", "items": {"$ref": "#/$defs/nope"}}}}
    with pytest.raises(UnsupportedSchemaError, match="does not resolve"):
        check_uploaded_schema_in_isolation(json.dumps(schema))


def test_check_uploaded_schema_accepts_a_legitimate_recursive_tree_schema_and_it_still_validates():
    """A schema describing a tree by referencing its own root is the ordinary way to do it, and
    must not be rejected: it only recurses as deep as the instance actually sent, which
    MAX_DOCUMENT_DEPTH already bounds. Checks both halves in one test: the schema uploads, and
    using it afterwards still tells good arguments from bad ones.
    """
    schema = {
        "type": "object",
        "required": ["value"],
        "properties": {"value": {"type": "integer"}, "child": {"$ref": "#"}},
    }

    check_uploaded_schema_in_isolation(json.dumps(schema))  # must not raise

    validate_arguments_in_isolation(schema, json.dumps({"value": 1, "child": {"value": 2}}))  # must not raise
    with pytest.raises(jsonschema.ValidationError):
        validate_arguments_in_isolation(schema, json.dumps({"value": 1, "child": {"value": "no"}}))


def test_check_uploaded_schema_accepts_a_plain_name_anchor_reference_and_it_still_validates():
    """A fragment after "#" is not always a JSON Pointer: "#itemAnchor" here names a "$anchor", a
    legitimate vendor pattern the specification itself recommends for recursive and extensible
    schemas, and jsonschema resolves it correctly on its own. find_unresolvable_ref must not treat
    it as a broken pointer and refuse the upload. Checks both halves: the schema uploads, and
    using it afterwards still tells good arguments from bad ones.
    """
    schema = {
        "type": "object",
        "$defs": {
            "item": {
                "$anchor": "itemAnchor",
                "type": "object",
                "required": ["n"],
                "properties": {"n": {"type": "integer"}},
            }
        },
        "properties": {"thing": {"$ref": "#itemAnchor"}},
    }

    check_uploaded_schema_in_isolation(json.dumps(schema))  # must not raise

    validate_arguments_in_isolation(schema, json.dumps({"thing": {"n": 1}}))  # must not raise
    with pytest.raises(jsonschema.ValidationError):
        validate_arguments_in_isolation(schema, json.dumps({"thing": {"n": "no"}}))


def test_check_uploaded_schema_accepts_a_subresource_with_its_own_id_and_it_still_validates():
    """An "$id" below the top level starts a separate resource, and a pointer written inside it
    resolves against that resource rather than against the whole document. Walking the document
    alone cannot see that, so "#/$defs/n" below named nothing at the top level and the upload was
    refused, while jsonschema resolved it and enforced the "string" it names. Checks both halves:
    the schema uploads, and using it afterwards still tells good arguments from bad ones.
    """
    schema = {
        "type": "object",
        "$defs": {
            "inner": {
                "$id": "https://example.invalid/inner",
                "$defs": {"n": {"type": "string"}},
                "$ref": "#/$defs/n",
            }
        },
        "properties": {"a": {"$ref": "#/$defs/inner"}},
    }

    check_uploaded_schema_in_isolation(json.dumps(schema))  # must not raise

    validate_arguments_in_isolation(schema, json.dumps({"a": "hello"}))  # must not raise
    with pytest.raises(jsonschema.ValidationError):
        validate_arguments_in_isolation(schema, json.dumps({"a": 1}))


def test_check_uploaded_schema_accepts_a_percent_encoded_pointer_and_it_still_validates():
    """A reference is a URI, so a "$defs" name holding a space is written "#/$defs/a%20b" by
    anything that builds one. Splitting the fragment without percent-decoding it first looked for a
    key literally called "a%20b", found nothing, and refused the upload, while jsonschema decoded
    the fragment and enforced the subschema it names. Checks both halves: the schema uploads, and
    using it afterwards still tells good arguments from bad ones.
    """
    schema = {
        "type": "object",
        "$defs": {"a b": {"type": "string"}},
        "properties": {"x": {"$ref": "#/$defs/a%20b"}},
    }

    check_uploaded_schema_in_isolation(json.dumps(schema))  # must not raise

    validate_arguments_in_isolation(schema, json.dumps({"x": "hello"}))  # must not raise
    with pytest.raises(jsonschema.ValidationError):
        validate_arguments_in_isolation(schema, json.dumps({"x": 1}))


def test_check_uploaded_schema_accepts_a_literal_value_holding_a_ref_key():
    """ "const", "default", "enum" and "examples" hold instance data, not subschemas, so a "$ref" key
    inside one is an ordinary object key that jsonschema never resolves.

    Both reference walks took any dict with a string "$ref" for a reference wherever it sat, so a
    function pinning a default or const object that happens to have a "$ref" key could never be
    uploaded at all, and the refusal named something that is not a reference: measured as "it
    contains a reference that does not resolve" for the const below and "it must not reference
    external resources" for the default.
    """
    schema = {
        "type": "object",
        "properties": {
            "cfg": {"const": {"$ref": "#/nope"}},
            "endpoint": {"default": {"$ref": "https://example.invalid/x.json"}},
        },
    }

    check_uploaded_schema_in_isolation(json.dumps(schema))  # must not raise


def test_check_uploaded_schema_still_rejects_a_bad_ref_under_a_property_named_like_a_keyword():
    """Skipping the literal-value keywords must not become a way to hide a reference behind one.

    A property may be named anything, including "const", and under "properties" that name is a name
    rather than the keyword: the schema beside it is evaluated normally, so a reference in there has
    to be caught. The walks therefore descend through the schemas a name-to-schema map holds instead
    of through the map itself, which is what keeps the two cases apart.
    """
    schema = {"type": "object", "properties": {"const": {"$ref": "https://example.invalid/x.json"}}}

    with pytest.raises(UnsupportedSchemaError, match="must not reference external resources"):
        check_uploaded_schema_in_isolation(json.dumps(schema))


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

    Without a cap the ceiling is settings.MAX_REQUEST_BODY_SIZE_MB, the bound on any request body,
    which is set for the whole API rather than for what one validation was measured against.
    """
    arguments = json.dumps({"blob": "x" * (settings.MAX_ARGUMENTS_LENGTH_MB * 1024 * 1024 + 1)})

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

    Also checks the message says something. A boolean schema is the one case where jsonschema leaves
    both fields the message is built from unset, so it used to come back as "'None' validation
    failed, schema requires None", naming neither a keyword nor a requirement.
    """
    program = MagicMock()
    program.arguments_schema = "false"

    with pytest.raises(InvalidArgumentsException) as caught:
        validate_arguments(program, '{"anything": 1}')
    assert "None" not in caught.value.message
    assert "rejects every value" in caught.value.message


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


def test_error_message_keeps_the_reason_for_a_large_rejected_value():
    """The previous fix (test_error_message_does_not_echo_the_whole_payload above) only bounded
    the message's length. jsonschema builds exc.message as f"{instance!r} <reason>", value first
    and reason last, so truncating the front to stay under the bound kept 500 characters of the
    rejected value and dropped the reason entirely: a 39 KB base64 encoded circuit came back with
    no explanation of what was wrong with it. The message must contain the reason regardless of
    how large the rejected value is, and still stay bounded.
    """
    schema = {"type": "object", "properties": {"blob": {"type": "integer"}}}
    arguments = json.dumps({"blob": "x" * 50_000})

    with pytest.raises(InvalidArgumentsException) as caught:
        validate_arguments(_program(schema), arguments)

    assert "integer" in caught.value.message
    assert len(caught.value.message) < 1000


def test_error_message_keeps_the_rejected_value_for_a_large_schema_requirement():
    """The fix above put the reason at the front by building the message from exc.validator and
    exc.validator_value rather than from exc.message. validator_value does not grow with the
    instance, which is what that fix was about, but it does grow with the schema: it is whatever the
    failing keyword required, so for "enum" it is the whole list of allowed values, and for "anyOf"
    or "properties" the whole subschema, up to MAX_SCHEMA_LENGTH.

    That put the schema at the front where the payload used to be, and the same 500 character
    truncation cut the message off at the same place, so an enum of a few hundred options came back
    as 500 characters of enum with the rejected value gone entirely. Both halves have to stay inside
    the bound, not just the one that was measured first.

    Both are large here, which is the worst case: the point of bounding them individually is that the
    whole message then fits under MAX_MESSAGE_LENGTH on its own, so the truncation in the use case
    never has anything to cut and no part of the message can be the part that gets lost.
    """
    schema = {"type": "object", "properties": {"x": {"enum": [f"option-{index}" for index in range(400)]}}}

    with pytest.raises(InvalidArgumentsException) as caught:
        validate_arguments(_program(schema), json.dumps({"x": "z" * 50_000}))

    assert "rejected value" in caught.value.message
    assert "(message truncated)" not in caught.value.message
    assert len(caught.value.message) < MAX_MESSAGE_LENGTH


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


def test_the_configured_limits_reach_the_child_clamped(settings, monkeypatch):
    """Both limits are read from settings so a deployment can tune them without a code deploy, and
    both are clamped so that the same setting cannot weaken them past a measured bound: 10000 CPU
    seconds is an unbounded request thread again, and 8 MB of memory would reject ordinary callers
    rather than attackers.

    Asserted on what _answer_from_child hands to run_isolated, with values outside the range in both
    directions. Configured values inside the range would not prove anything here: with 3 and 200 this
    test passed against raw settings reads with the clamp deleted from the production path.
    """
    real_run_isolated = arguments_schema_module.run_isolated
    seen = {}

    def spy(work, **kwargs):
        seen.update(kwargs)
        return real_run_isolated(work, **kwargs)

    monkeypatch.setattr(arguments_schema_module, "run_isolated", spy)

    settings.ARGUMENTS_SCHEMA_CPU_LIMIT_SECONDS = 10000
    settings.ARGUMENTS_SCHEMA_MEMORY_LIMIT_MB = 100000
    validate_arguments_in_isolation({"type": "object"}, "{}")
    assert seen == {"cpu_seconds": 5, "memory_mb": 256}

    settings.ARGUMENTS_SCHEMA_CPU_LIMIT_SECONDS = 0
    settings.ARGUMENTS_SCHEMA_MEMORY_LIMIT_MB = 8
    validate_arguments_in_isolation({"type": "object"}, "{}")
    assert seen == {"cpu_seconds": 1, "memory_mb": 64}


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
