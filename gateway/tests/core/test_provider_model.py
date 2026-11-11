"""Tests for the Provider model."""

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings

from core.models import Provider
from tests.utils import TestUtils

pytestmark = pytest.mark.django_db


def _provider(project_name):
    project = TestUtils.get_or_create_ce_project(project_name=project_name, project_id=f"id-{project_name}")
    return Provider(name="acme", code_engine_project=project)


@override_settings(CE_DEFAULT_PROJECT_NAME="qiskit-functions")
def test_a_provider_cannot_take_the_shared_default_project():
    with pytest.raises(ValidationError) as error:
        _provider("qiskit-functions").clean()

    assert list(error.value.message_dict) == ["code_engine_project"]


@override_settings(CE_DEFAULT_PROJECT_NAME="qiskit-functions")
def test_a_provider_can_take_its_own_project():
    _provider("acme-project").clean()
