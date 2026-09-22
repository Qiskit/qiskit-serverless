"""Tests for the data migration that uppercases pre-existing FunctionSize rows.

FunctionSize.save()/from_db() already make every row look uppercase from application code
regardless of what is actually stored, so this migration is a one-time cleanup, not something
correctness depends on going forward. These tests call its RunPython function directly against
the real app registry, since this repo has no migration-state test harness and the function's
own logic (read raw, decide, write raw) does not depend on historical model fields.
"""

import importlib

import pytest
from django.apps import apps as live_apps

from core.models import ComputeProfile, FunctionSize
from tests.utils import TestUtils

pytestmark = pytest.mark.django_db

_migration = importlib.import_module("api.migrations.0066_function_size_uppercase_catalog")


@pytest.fixture
def program():
    return TestUtils.create_program(program_title="legacy-sized-function", author="migration_test_user")


@pytest.fixture
def other_program():
    return TestUtils.create_program(program_title="other-legacy-sized-function", author="migration_test_user")


@pytest.fixture
def profile():
    return ComputeProfile.objects.create(compute_profile_id="16x128", cpu="16", memory="128")


def test_lowercase_row_is_uppercased(program, profile):
    """A row written under the old lowercase convention is rewritten to uppercase."""
    size = FunctionSize.objects.create(function=program, function_size="M", compute_profile=profile)
    FunctionSize.objects.filter(pk=size.pk).update(function_size="m")

    _migration.uppercase_existing_function_sizes(live_apps, schema_editor=None)

    assert FunctionSize.objects.filter(pk=size.pk).values_list("function_size", flat=True).get() == "M"


def test_row_with_an_existing_uppercase_sibling_is_left_alone(program, other_program, profile):
    """A lowercase row is skipped, not merged or deleted, if its function already has the uppercase form.

    Two rows for the same function must never collide under unique_function_size, so the
    migration leaves the ambiguous pair for an operator to resolve rather than guessing.
    """
    existing_upper = FunctionSize.objects.create(function=program, function_size="M", compute_profile=profile)
    stray_lower = FunctionSize.objects.create(function=program, function_size="L", compute_profile=profile)
    FunctionSize.objects.filter(pk=stray_lower.pk).update(function_size="m")
    # A different function's row is unaffected either way -- collisions are scoped per function.
    FunctionSize.objects.create(function=other_program, function_size="m", compute_profile=profile)

    _migration.uppercase_existing_function_sizes(live_apps, schema_editor=None)

    assert FunctionSize.objects.filter(pk=stray_lower.pk).values_list("function_size", flat=True).get() == "m"
    assert FunctionSize.objects.filter(pk=existing_upper.pk).values_list("function_size", flat=True).get() == "M"
