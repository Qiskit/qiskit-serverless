"""Unit tests for validate_arguments and ValidateArgumentsUseCase."""

import json
import pytest
from unittest.mock import MagicMock
from django.contrib.auth.models import User

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
