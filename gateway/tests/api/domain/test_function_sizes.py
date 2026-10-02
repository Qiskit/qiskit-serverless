"""Tests for the function size catalog validation in parse_function_sizes."""

import pytest

from api.domain.exceptions.invalid_function_sizes_error import InvalidFunctionSizesError
from api.domain.function_sizes import parse_function_sizes


def test_size_outside_catalog_is_rejected():
    """A size name outside {S, M, L, XL} is rejected, whatever its case."""
    with pytest.raises(InvalidFunctionSizesError) as exc_info:
        parse_function_sizes({"tiny": "16x128"})

    assert "tiny" in str(exc_info.value)
    assert "S, M, L, XL" in str(exc_info.value)


def test_valid_size_name_normalizes_case_insensitively():
    """A valid size in any case still normalizes to its uppercase canonical form."""
    assert parse_function_sizes({"m": "16x128"}) == {"M": "16x128"}
