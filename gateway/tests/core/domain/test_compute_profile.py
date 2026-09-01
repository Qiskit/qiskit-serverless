"""Unit tests for compute profile validation and normalization."""

import pytest

from core.domain import compute_profile


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
def test_normalize(value, expected):
    assert compute_profile.normalize(value) == expected


def test_normalize_is_idempotent():
    once = compute_profile.normalize("bx3d-24x120")
    assert compute_profile.normalize(once) == once


@pytest.mark.parametrize(
    "value",
    [
        "bx3d-24x120",
        "cx3d-4x16",
        "gx3d-24x120x1a100p",
        "mx2d-8x64",
        "bx2d-2x8",
        "4x16",
        "24x120x1a100p",
    ],
)
def test_is_valid_accepts_prefixed_and_bare_forms(value):
    assert compute_profile.is_valid(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "invalid",
        "CX3D-4x16",  # uppercase not allowed
        "cx3d_4x16",  # underscore not allowed
        "cx3d-4",  # missing memory spec
        "4",  # missing memory spec (bare)
        "",  # empty string
        None,
    ],
)
def test_is_valid_rejects_malformed_values(value):
    assert compute_profile.is_valid(value) is False
