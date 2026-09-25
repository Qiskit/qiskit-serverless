"""Tests for the ComputeProfile and FunctionSize models.

Covers the relational contracts between ``Program``, ``FunctionSize`` and
``ComputeProfile``. The ``ComputeProfile`` table ships empty — rows are created
by operators — so these tests build their own fixtures.
"""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from core.models import ComputeProfile, FunctionSize, Program
from tests.utils import TestUtils

pytestmark = pytest.mark.django_db


@pytest.fixture
def program():
    """Create a program owned by a fresh test user."""
    return TestUtils.create_program(program_title="test-sized-function", author="size_test_user")


@pytest.fixture
def other_program():
    """Create a second, unrelated program."""
    return TestUtils.create_program(program_title="other-sized-function", author="size_test_user")


@pytest.fixture
def profile():
    """Create a CPU-only compute profile."""
    return ComputeProfile.objects.create(compute_profile_id="16x128", cpu="16", memory="128")


@pytest.fixture
def other_profile():
    """Create a CPU-only compute profile."""
    return ComputeProfile.objects.create(compute_profile_id="128x1500", cpu="128", memory="1500")


def test_create_profile_without_optional_fields():
    """A profile saves without setting ``name`` or ``gpu``.

    Regression test: these columns previously declared ``default=None`` while
    being NOT NULL, which made every such insert fail.
    """
    compute_profile = ComputeProfile.objects.create(compute_profile_id="8x32", cpu="8", memory="32")

    compute_profile.refresh_from_db()
    assert compute_profile.name == ""
    assert compute_profile.gpu is None


def test_create_profile_with_gpu():
    """A GPU profile stores the count-prefixed model verbatim."""
    compute_profile = ComputeProfile.objects.create(
        compute_profile_id="24x120x1l40s", cpu="24", memory="120", gpu="1l40s"
    )

    compute_profile.refresh_from_db()
    assert compute_profile.gpu == "1l40s"


def test_duplicate_function_size_rejected(program, profile):
    """``(function, function_size)`` is unique."""
    FunctionSize.objects.create(function=program, function_size="m", compute_profile=profile)

    with pytest.raises(IntegrityError):
        FunctionSize.objects.create(function=program, function_size="m", compute_profile=profile)


def test_same_size_keyword_allowed_for_different_functions(program, other_program, profile, other_profile):
    """The uniqueness constraint is per function, not global."""
    FunctionSize.objects.create(function=program, function_size="m", compute_profile=profile)
    FunctionSize.objects.create(function=other_program, function_size="m", compute_profile=other_profile)

    assert FunctionSize.objects.filter(function_size="m").count() == 2


def test_deleting_program_cascades_to_its_sizes(program, profile):
    """Sizes belong to their function and go away with it."""
    FunctionSize.objects.create(function=program, function_size="m", compute_profile=profile)

    program.delete()

    assert not FunctionSize.objects.filter(function_id=program.pk).exists()


def test_default_size_from_another_function_is_rejected(program, other_program, profile):
    """A cross-function default is rejected by ``Program.clean``."""
    program.default_size = FunctionSize.objects.create(
        function=other_program, function_size="m", compute_profile=profile
    )

    with pytest.raises(ValidationError) as exc_info:
        program.full_clean()

    assert "default_size" in exc_info.value.message_dict


def test_referenced_compute_profile_is_protected(program, profile):
    """A profile in use cannot be deleted."""
    FunctionSize.objects.create(function=program, function_size="m", compute_profile=profile)

    with pytest.raises(ProtectedError):
        with transaction.atomic():
            profile.delete()

    assert ComputeProfile.objects.filter(pk="16x128").exists()
