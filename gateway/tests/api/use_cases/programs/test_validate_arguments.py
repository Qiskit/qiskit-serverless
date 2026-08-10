"""Unit tests for validate_arguments and ValidateArgumentsUseCase."""

import json
import time
import pytest
from unittest.mock import MagicMock
from django.contrib.auth.models import User

from api.domain.arguments_schema import MAX_ARGUMENTS_LENGTH, MAX_SCHEMA_LENGTH
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.domain.exceptions.invalid_arguments_exception import InvalidArgumentsException
from api.use_cases.programs.validate_arguments import ValidateArgumentsUseCase, validate_arguments
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Program


def _program(schema_dict):
    p = MagicMock()
    p.arguments_schema = json.dumps(schema_dict)
    return p


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
    schema = {"type": "object", "required": ["shots"]}
    with pytest.raises(InvalidArgumentsException):
        validate_arguments(_program(schema), "not-valid-json{{{")


def test_catastrophic_pattern_is_matched_in_linear_time():
    """A nested quantifier must not make validation exponential in the length of the input.

    Under Python's backtracking engine this pattern needs about 8 seconds for 28 characters and
    doubles per extra character, so 5000 characters would never finish. RE2 does not backtrack.
    """
    schema = {"type": "object", "properties": {"x": {"type": "string", "pattern": "^(a+)+$"}}}
    start = time.perf_counter()

    with pytest.raises(InvalidArgumentsException):
        validate_arguments(_program(schema), json.dumps({"x": "a" * 5000 + "!"}))

    assert time.perf_counter() - start < 1


def test_dialect_switch_below_the_top_level_is_rejected():
    """'$schema' in a subschema would switch jsonschema back to the backtracking engine."""
    schema = {
        "properties": {
            "x": {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "string",
                "pattern": "^(a+)+$",
            }
        }
    }
    with pytest.raises(InvalidArgumentsException, match=r"\$schema"):
        validate_arguments(_program(schema), '{"x": "aaa"}')


def test_pattern_properties_is_rejected():
    """'patternProperties' regexes stay reachable from Python's re engine, so the keyword is out."""
    schema = {"type": "object", "patternProperties": {"^(a+)+$": {"type": "integer"}}}
    with pytest.raises(InvalidArgumentsException, match="patternProperties"):
        validate_arguments(_program(schema), json.dumps({"a" * 5000 + "!": 1}))


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


def test_external_ref_is_rejected_without_being_fetched():
    """A stored schema pointing at a URL must not make the gateway fetch it (SSRF).

    The error says the reference is unresolvable, which can only happen if no retrieval was
    attempted: a successful fetch would have produced a schema and validated against it.
    """
    schema = {"$ref": "http://169.254.169.254/latest/meta-data/"}
    with pytest.raises(InvalidArgumentsException, match="cannot be resolved"):
        validate_arguments(_program(schema), '{"shots": 1024}')


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
    """A stored schema that is not a valid JSON Schema must not surface as a 500."""
    with pytest.raises(InvalidArgumentsException, match="not usable"):
        validate_arguments(_program({"type": "integar"}), '{"shots": 1024}')


def test_non_string_pattern_is_reported_instead_of_crashing():
    """A 'pattern' that is not a string must not reach the regex engine and raise a TypeError."""
    with pytest.raises(InvalidArgumentsException):
        validate_arguments(_program({"properties": {"x": {"pattern": {"nope": 1}}}}), '{"x": "v"}')


def test_combinatorial_ref_bomb_is_cut_off():
    """A small schema can express an exponential combination through internal references.

    Eighteen levels of two-branch 'anyOf' fit in 1.3 KB, well under the length limit, and take
    minutes to evaluate without a budget on how many subschemas a validation may visit.
    """
    defs = {"l0": {"anyOf": [{"type": "string"}, {"type": "string"}]}}
    for level in range(1, 19):
        ref = {"$ref": f"#/$defs/l{level - 1}"}
        defs[f"l{level}"] = {"anyOf": [ref, ref]}
    schema = {"$defs": defs, "$ref": "#/$defs/l18"}
    start = time.perf_counter()

    with pytest.raises(InvalidArgumentsException, match="subschemas"):
        validate_arguments(_program(schema), "123")

    assert time.perf_counter() - start < 1


def test_arguments_longer_than_the_limit_are_rejected():
    """The work a validation does grows with the caller's payload, so its length is capped.

    Without a cap the ceiling is DATA_UPLOAD_MAX_MEMORY_SIZE, 2.5 MB by default, which is three
    orders of magnitude more input than any keyword was measured against.
    """
    arguments = json.dumps({"blob": "x" * (MAX_ARGUMENTS_LENGTH + 1)})

    with pytest.raises(InvalidArgumentsException, match="maximum"):
        validate_arguments(_program({"type": "object"}), arguments)


def test_unique_items_on_a_large_array_of_objects_stays_cheap():
    """'uniqueItems' compares values pairwise when they are not orderable, which is quadratic.

    An array of objects is the ordinary case that triggers it, and it never descends into a
    subschema, so the step budget does not see it: 4000 items took about 8 seconds and 8000 more
    than 30, with a schema anyone would write and one step spent.
    """
    arguments = json.dumps([{"i": i} for i in range(4000)])
    start = time.perf_counter()

    validate_arguments(_program({"type": "array", "uniqueItems": True}), arguments)  # must not raise

    assert time.perf_counter() - start < 2


def test_unevaluated_properties_is_rejected():
    """'unevaluatedProperties' works out which keys were evaluated inside a private jsonschema helper.

    That helper recurses through '$ref' and 'dependentSchemas' without ever descending into a
    subschema, so the step budget cannot see the work. Because the keyword comes first in the
    document its error is the one that stops the validation, so validation never does its own walk
    of the same chain: 1.5 KB spent 1.7 seconds while using 2 of the 10000 steps, and every extra
    level doubles it. The identical chain without the keyword is cut off at 10000 steps in 0.05s.
    The keyword has to go the way of 'patternProperties': its cost is not observable.
    """
    defs = {"l0": {"type": "object"}}
    for level in range(1, 18):
        ref = {"$ref": f"#/$defs/l{level - 1}"}
        defs[f"l{level}"] = {"$ref": f"#/$defs/l{level - 1}", "dependentSchemas": {"a": ref}}
    schema = {
        "unevaluatedProperties": False,
        "dependentSchemas": {"a": {"$ref": "#/$defs/l17"}},
        "$defs": defs,
    }
    start = time.perf_counter()

    with pytest.raises(InvalidArgumentsException, match="unevaluatedProperties"):
        validate_arguments(_program(schema), '{"a": 1}')

    assert time.perf_counter() - start < 1


def test_unevaluated_items_is_rejected():
    """Same as 'unevaluatedProperties': the sibling keyword costs just as much and just as quietly."""
    with pytest.raises(InvalidArgumentsException, match="unevaluatedItems"):
        validate_arguments(_program({"type": "array", "unevaluatedItems": False}), "[1, 2]")


def test_unique_items_still_catches_a_duplicate():
    """Replacing the keyword must not turn it into a keyword that accepts everything."""
    with pytest.raises(InvalidArgumentsException):
        validate_arguments(_program({"type": "array", "uniqueItems": True}), '[{"i": 1}, {"i": 1}]')


def test_budget_is_reset_between_validations():
    """The step counter must not leak across calls, or a later validation would fail unfairly."""
    schema = {"type": "object", "properties": {"shots": {"type": "integer"}}}
    for _ in range(3):
        validate_arguments(_program(schema), '{"shots": 1024}')  # must not raise


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
