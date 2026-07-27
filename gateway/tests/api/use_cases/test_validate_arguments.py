"""Unit tests for validate_arguments use case."""

import json
import pytest
from unittest.mock import MagicMock

from api.domain.exceptions.invalid_arguments_exception import InvalidArgumentsException
from api.use_cases.validate_arguments import validate_arguments


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
