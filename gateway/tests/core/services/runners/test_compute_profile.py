"""Unit tests for compute profile normalization."""

import pytest

from core.services.runners.compute_profile import normalize_compute_profile


@pytest.mark.parametrize(
    "value,expected",
    [
        ("bx3d-24x120", "24x120"),
        ("cx3d-4x16", "4x16"),
        ("gx3d-24x120x1a100p", "24x120x1a100p"),
        # Already-bare values pass through unchanged (idempotent).
        ("24x120", "24x120"),
        ("24x120x1a100p", "24x120x1a100p"),
        # Empty / missing -> None.
        (None, None),
        ("", None),
    ],
)
def test_normalize_compute_profile(value, expected):
    assert normalize_compute_profile(value) == expected


def test_normalize_is_idempotent():
    once = normalize_compute_profile("bx3d-24x120")
    assert normalize_compute_profile(once) == once
