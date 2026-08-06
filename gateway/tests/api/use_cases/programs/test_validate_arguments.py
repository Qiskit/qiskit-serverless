"""Unit tests for validate_arguments and ValidateArgumentsUseCase."""

import json
import time
import pytest
from unittest.mock import MagicMock
from django.contrib.auth.models import User

from api.domain.arguments_schema import MAX_SCHEMA_LENGTH
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
