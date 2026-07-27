"""Tests for the Program admin form."""

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test.client import RequestFactory

from api.admin import ProgramAdmin
from core.models import Program, Provider


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
