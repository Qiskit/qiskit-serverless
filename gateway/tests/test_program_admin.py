"""Tests for the Program admin form."""

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test.client import RequestFactory
from django.urls import reverse

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


@pytest.mark.django_db
def test_opening_a_function_with_a_broken_schema_shows_the_reason():
    """A row that is already broken should stop being invisible."""
    program = _program(arguments_schema="not json at all")
    form_class = ProgramAdmin(Program, AdminSite()).get_form(RequestFactory().get("/"), obj=program)

    form = form_class(instance=program)

    assert form.stored_schema_error == "arguments_schema cannot be used: it must be valid JSON."
    assert "it must be valid JSON" in form.fields["arguments_schema"].help_text


@pytest.mark.django_db
def test_the_stored_schema_is_not_checked_while_handling_a_submission():
    """One fork per page opened, none per save.

    Skipping this on a bound form also avoids a confusing message: after fixing the schema and
    hitting another validation error, the warning would still be describing the old value.
    """
    program = _program(arguments_schema="not json at all")
    form_class = ProgramAdmin(Program, AdminSite()).get_form(RequestFactory().get("/"), obj=program)

    form = form_class(data={"arguments_schema": '{"type": "object"}'}, instance=program)

    assert form.stored_schema_error is None


@pytest.mark.django_db
def test_the_change_page_warns_about_a_broken_stored_schema(client):
    """Exercise the real page, which is the only thing that proves the warning is rendered.

    The form attribute alone would not catch a `render_change_form` that never runs or a template
    with nowhere to put the message.
    """
    program = _program(arguments_schema="not json at all")
    client.force_login(User.objects.create_superuser(username="admin", password="x", email="a@b.c"))

    response = client.get(reverse("admin:api_program_change", args=[program.pk]))

    assert response.status_code == 200
    # Read the messages themselves, not the page text: the reason also reaches the HTML through the
    # field's help_text, so looking for it in the body would pass with no warning at all.
    warnings = [str(message) for message in response.context["messages"] if message.level_tag == "warning"]
    assert warnings == ["arguments_schema cannot be used: it must be valid JSON."]
