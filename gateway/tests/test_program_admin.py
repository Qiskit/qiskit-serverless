"""Tests for the Program admin form."""

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test.client import RequestFactory

from api.admin import ProgramAdmin
from core.models import Program, Provider


def _program(arguments_schema: str) -> Program:
    """Store a Program carrying `arguments_schema`, straight through the ORM so nothing validates it.

    Fixed names are fine: every test runs in its own transaction, so there is nothing to collide with.
    """
    user = User.objects.create_user(username="u", password="x")
    provider = Provider.objects.create(name="P")
    return Program.objects.create(title="t", author=user, provider=provider, arguments_schema=arguments_schema)


@pytest.mark.django_db
def test_title_editable_on_add_and_readonly_on_change():
    """`title` must be present and editable when creating a program, and
    read-only (still visible) when editing an existing one."""
    admin = ProgramAdmin(Program, AdminSite())
    request = RequestFactory().get("/")

    add_form = admin.get_form(request, obj=None)
    assert "title" in add_form.base_fields
    assert "title" not in admin.get_readonly_fields(request, obj=None)

    user = User.objects.create_user(username="u", password="x")
    provider = Provider.objects.create(name="P")
    program = Program.objects.create(title="t", author=user, provider=provider)
    assert "title" in admin.get_readonly_fields(request, obj=program)


@pytest.mark.django_db
def test_admin_rejects_a_schema_that_is_not_json():
    """The value that breaks client.functions() for everyone must not be storable."""
    program = _program(arguments_schema="{}")
    form_class = ProgramAdmin(Program, AdminSite()).get_form(RequestFactory().get("/"), obj=program)

    form = form_class(data={"arguments_schema": "not json at all"}, instance=program)

    assert not form.is_valid()
    assert form.errors["arguments_schema"] == ["arguments_schema cannot be used: it must be valid JSON."]


@pytest.mark.django_db
def test_admin_rejects_a_schema_that_only_fails_when_evaluated():
    """`{"$ref": "#"}` is valid JSON and a valid JSON Schema; it recurses without end when used.

    Asserting the message, and not just that the form is invalid, is what tells a rejection by our
    own validation apart from a failure for any other reason.
    """
    program = _program(arguments_schema="{}")
    form_class = ProgramAdmin(Program, AdminSite()).get_form(RequestFactory().get("/"), obj=program)

    form = form_class(data={"arguments_schema": '{"$ref": "#"}'}, instance=program)

    assert not form.is_valid()
    assert form.errors["arguments_schema"][0].startswith("arguments_schema cannot be used:")


@pytest.mark.django_db
def test_admin_accepts_a_valid_schema():
    """The happy path: a usable schema raises no complaint about the field."""
    program = _program(arguments_schema="{}")
    form_class = ProgramAdmin(Program, AdminSite()).get_form(RequestFactory().get("/"), obj=program)

    form = form_class(data={"arguments_schema": '{"type": "object"}'}, instance=program)

    form.is_valid()
    assert "arguments_schema" not in form.errors


@pytest.mark.django_db
def test_admin_lets_you_edit_a_function_whose_stored_schema_is_broken():
    """Disabling a broken function must not be blocked by the schema it already has.

    The schema is only checked when the field itself changes, so sending back the same stored value
    leaves it out of `changed_data` and out of the errors.
    """
    program = _program(arguments_schema="not json at all")
    form_class = ProgramAdmin(Program, AdminSite()).get_form(RequestFactory().get("/"), obj=program)

    form = form_class(data={"arguments_schema": "not json at all", "disabled": "on"}, instance=program)

    form.is_valid()
    assert "arguments_schema" not in form.changed_data
    assert "arguments_schema" not in form.errors
