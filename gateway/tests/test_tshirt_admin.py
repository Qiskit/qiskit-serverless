"""Tests for the T-shirt size elements of the backoffice admin.

Covers the function size catalog (the sizes map) surfaced on the Program page, the ``default_size``
dropdown restricted to a function's own sizes, and the reference count shown on ComputeProfile.
"""

import itertools

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test.client import RequestFactory
from django.urls import reverse

from api.admin import ComputeProfileAdmin, ProgramAdmin
from core.models import ComputeProfile, FunctionSize, Program, Provider

# Unique per call so a test can make more than one function without colliding on username/provider.
_counter = itertools.count()


def _function() -> Program:
    """A Fleets function with an author and provider, stored straight through the ORM."""
    n = next(_counter)
    user = User.objects.create_user(username=f"u{n}", password="x")
    provider = Provider.objects.create(name=f"P{n}")
    return Program.objects.create(title=f"t{n}", author=user, provider=provider, runner=Program.FLEETS)


def _profile(compute_profile_id: str = "8x32") -> ComputeProfile:
    return ComputeProfile.objects.create(compute_profile_id=compute_profile_id, cpu="8", memory="32")


def _size(function: Program, name: str, profile: ComputeProfile) -> FunctionSize:
    return FunctionSize.objects.create(function=function, function_size=name, compute_profile=profile)


@pytest.mark.django_db
def test_default_size_dropdown_is_limited_to_this_functions_sizes():
    """The default must belong to the same function (Program.clean()), so only its own sizes
    may appear in the dropdown — never sizes declared by some other function."""
    function = _function()
    profile = _profile()
    mine = _size(function, "s", profile)

    other = _function()
    _size(other, "s", profile)  # a different function's size must not leak into the dropdown

    admin = ProgramAdmin(Program, AdminSite())
    request = RequestFactory().get(reverse("admin:api_program_change", args=[function.pk]))
    request.resolver_match = type("M", (), {"kwargs": {"object_id": str(function.pk)}})

    form_class = admin.get_form(request, obj=function)
    choices = form_class().fields["default_size"].queryset

    assert list(choices) == [mine]


@pytest.mark.django_db
def test_default_size_dropdown_is_empty_on_the_add_form():
    """A function that does not exist yet has no sizes, so nothing is offered as a default."""
    admin = ProgramAdmin(Program, AdminSite())
    request = RequestFactory().get(reverse("admin:api_program_add"))
    request.resolver_match = type("M", (), {"kwargs": {}})

    form_class = admin.get_form(request, obj=None)

    assert list(form_class().fields["default_size"].queryset) == []


@pytest.mark.django_db
def test_sizes_summary_reports_count_and_default():
    """The changelist column shows how many sizes are declared and which one is the default."""
    function = _function()
    profile = _profile()
    small = _size(function, "s", profile)
    _size(function, "m", profile)
    function.default_size = small
    function.save(update_fields=["default_size"])

    admin = ProgramAdmin(Program, AdminSite())
    request = RequestFactory().get(reverse("admin:api_program_changelist"))
    obj = admin.get_queryset(request).get(pk=function.pk)

    assert admin.sizes_summary(obj) == "2 (default: s)"


@pytest.mark.django_db
def test_sizes_summary_is_a_dash_when_no_sizes_are_declared():
    """A function without a size catalog reads as '-' rather than '0 (default: none)'."""
    function = _function()
    admin = ProgramAdmin(Program, AdminSite())
    request = RequestFactory().get(reverse("admin:api_program_changelist"))
    obj = admin.get_queryset(request).get(pk=function.pk)

    assert admin.sizes_summary(obj) == "-"


@pytest.mark.django_db
def test_the_change_page_shows_the_size_catalog_inline(client):
    """The whole sizes map is visible on the function page, not only on the FunctionSize list."""
    function = _function()
    profile = _profile("24x120x1l40s")
    _size(function, "l", profile)
    client.force_login(User.objects.create_superuser(username="admin", password="x", email="a@b.c"))

    response = client.get(reverse("admin:api_program_change", args=[function.pk]))

    assert response.status_code == 200
    body = response.content.decode()
    assert "24x120x1l40s" in body
    assert "Sizes (compute profile per size)" in body


@pytest.mark.django_db
def test_the_change_page_offers_only_this_functions_sizes_as_default(client):
    """End-to-end through the real admin URL: the default_size dropdown on the rendered page lists
    this function's own size and not another function's, proving object_id reaches the formfield."""
    function = _function()
    profile = _profile()
    _size(function, "mine", profile)

    other = _function()
    _size(other, "theirs", profile)

    client.force_login(User.objects.create_superuser(username="admin", password="x", email="a@b.c"))
    response = client.get(reverse("admin:api_program_change", args=[function.pk]))

    default_field = response.context["adminform"].form.fields["default_size"]
    labels = [str(obj) for obj in default_field.queryset]
    assert any("mine" in label for label in labels)
    assert not any("theirs" in label for label in labels)


@pytest.mark.django_db
def test_compute_profile_reports_how_many_sizes_use_it():
    """An operator must see a profile is referenced before editing it (the FK is PROTECT)."""
    function = _function()
    profile = _profile()
    _size(function, "s", profile)
    _size(function, "m", profile)

    admin = ComputeProfileAdmin(ComputeProfile, AdminSite())
    request = RequestFactory().get(reverse("admin:api_computeprofile_changelist"))
    obj = admin.get_queryset(request).get(pk=profile.pk)

    assert admin.sizes_using(obj) == 2
