"""Tests for the T-shirt size elements of the backoffice admin.

Covers the function size catalog (the sizes map) surfaced on the Program page, the ``default_size``
dropdown restricted to a function's own sizes, and the reference count shown on ComputeProfile.
"""

import itertools
from types import SimpleNamespace

import pytest
from django import forms
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import override_settings
from django.test.client import RequestFactory
from django.urls import reverse

from api.admin import ComputeProfileAdmin, ProgramAdmin, ProgramAdminForm
from core.models import CodeEngineProject, ComputeProfile, FunctionSize, Program, Provider

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


def _ce_project(name: str = "ce-proj", active: bool = True) -> CodeEngineProject:
    """A minimally-populated active Code Engine project (CharFields default to '')."""
    return CodeEngineProject.objects.create(
        project_id=f"{name}-id",
        project_name=name,
        region="us-east",
        active=active,
    )


def _request_with_messages():
    """A request the admin can attach messages to (save_related emits warnings)."""
    request = RequestFactory().post("/")
    setattr(request, "session", {})
    setattr(request, "_messages", FallbackStorage(request))
    return request


def _messages(request) -> list[str]:
    return [str(m) for m in request._messages]


def _save_related(admin: ProgramAdmin, request, obj: Program, change: bool = False) -> None:
    """Drive ProgramAdmin.save_related with a stub form; inlines are written separately in the test.

    super().save_related calls form.save_m2m(); the instance has no unsaved m2m here, so a no-op
    stub is enough to reach the seeding logic under test.
    """
    form = SimpleNamespace(instance=obj, save_m2m=lambda: None)
    admin.save_related(request, form, formsets=[], change=change)


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


# --- Making a backoffice-created Fleets function runnable -------------------------------------
#
# ProgramAdminForm.clean() assigns a Code Engine project (like the upload endpoint) and blocks the
# save when none is available; ProgramAdmin.save_related() seeds a default size for a size-less
# Fleets function. These tests exercise clean() directly with a set cleaned_data (bypassing the
# per-field validation of an "__all__" ModelForm), and drive save_related with a stub form.


def _clean_program_form(instance: Program, cleaned_data: dict) -> ProgramAdminForm:
    """Run ProgramAdminForm.clean() against a prepared instance + cleaned_data.

    Returns the form so callers can inspect .cleaned_data; clean() raises ValidationError to block.
    """
    form = ProgramAdminForm(instance=instance)
    form.cleaned_data = cleaned_data
    form.cleaned_data = form.clean()
    return form


@pytest.mark.django_db
def test_clean_assigns_the_providers_active_ce_project():
    """A Fleets function with a provider and no chosen project gets the provider's active project."""
    provider = Provider.objects.create(name="prov", code_engine_project=_ce_project("prov-proj"))
    program = Program(title="fn", runner=Program.FLEETS, provider=provider)

    form = _clean_program_form(program, {"runner": Program.FLEETS, "provider": provider, "code_engine_project": None})

    assert form.cleaned_data["code_engine_project"].project_name == "prov-proj"


@pytest.mark.django_db
@override_settings(CE_DEFAULT_PROJECT_NAME="default-proj")
def test_clean_assigns_the_default_ce_project_when_providerless():
    """A providerless Fleets function gets the configured default project."""
    default_project = _ce_project("default-proj")
    program = Program(title="fn", runner=Program.FLEETS, provider=None)

    form = _clean_program_form(program, {"runner": Program.FLEETS, "provider": None, "code_engine_project": None})

    assert form.cleaned_data["code_engine_project"] == default_project


@pytest.mark.django_db
@override_settings(CE_DEFAULT_PROJECT_NAME="")
def test_clean_blocks_the_save_when_default_project_is_unconfigured():
    """An unconfigured CE_DEFAULT_PROJECT_NAME makes select_default() raise; the save is refused,
    not 500'd."""
    program = Program(title="fn", runner=Program.FLEETS, provider=None)

    with pytest.raises(forms.ValidationError) as exc:
        _clean_program_form(program, {"runner": Program.FLEETS, "provider": None, "code_engine_project": None})

    assert "No active Code Engine project available" in str(exc.value)


@pytest.mark.django_db
def test_clean_blocks_the_save_when_provider_has_no_project():
    """A Fleets function whose provider has no project cannot be saved."""
    provider = Provider.objects.create(name="prov", code_engine_project=None)
    program = Program(title="fn", runner=Program.FLEETS, provider=provider)

    with pytest.raises(forms.ValidationError) as exc:
        _clean_program_form(program, {"runner": Program.FLEETS, "provider": provider, "code_engine_project": None})

    assert "No active Code Engine project for provider 'prov'" in str(exc.value)


@pytest.mark.django_db
def test_clean_blocks_the_save_when_providers_project_is_inactive():
    """An inactive provider project is treated as no project, with its own message."""
    provider = Provider.objects.create(name="prov", code_engine_project=_ce_project("prov-proj", active=False))
    program = Program(title="fn", runner=Program.FLEETS, provider=provider)

    with pytest.raises(forms.ValidationError) as exc:
        _clean_program_form(program, {"runner": Program.FLEETS, "provider": provider, "code_engine_project": None})

    assert "is not active" in str(exc.value)


@pytest.mark.django_db
def test_clean_keeps_an_operator_chosen_project():
    """A project the operator picked is left untouched (assign_to_program no-ops)."""
    chosen = _ce_project("chosen")
    program = Program(title="fn", runner=Program.FLEETS, provider=None)

    form = _clean_program_form(program, {"runner": Program.FLEETS, "provider": None, "code_engine_project": chosen})

    assert form.cleaned_data["code_engine_project"] == chosen


@pytest.mark.django_db
def test_clean_ignores_ray_functions():
    """A Ray function needs no CE project and must not be blocked or assigned one."""
    program = Program(title="fn", runner=Program.RAY, provider=None)

    form = _clean_program_form(program, {"runner": Program.RAY, "provider": None, "code_engine_project": None})

    assert form.cleaned_data.get("code_engine_project") is None


@pytest.mark.django_db
@override_settings(DEFAULT_FUNCTION_SIZE="m", DEFAULT_FUNCTION_SIZE_PROFILE="16x128")
def test_save_related_seeds_a_default_size_when_none_declared():
    """A size-less Fleets function gets the deployment default size, like the upload path."""
    _profile("16x128")
    function = _function()
    request = _request_with_messages()

    _save_related(ProgramAdmin(Program, AdminSite()), request, function)

    function.refresh_from_db()
    sizes = list(FunctionSize.objects.filter(function=function))
    assert len(sizes) == 1
    assert sizes[0].function_size == "m"
    assert sizes[0].compute_profile_id == "16x128"
    assert function.default_size_id == sizes[0].id
    assert _messages(request) == []


@pytest.mark.django_db
@override_settings(DEFAULT_FUNCTION_SIZE="m", DEFAULT_FUNCTION_SIZE_PROFILE="16x128")
def test_save_related_warns_when_the_default_profile_is_not_registered():
    """Seeding is non-fatal: no profile row means no size and a warning, not a crash."""
    function = _function()  # note: no ComputeProfile "16x128" created
    request = _request_with_messages()

    _save_related(ProgramAdmin(Program, AdminSite()), request, function)

    function.refresh_from_db()
    assert not FunctionSize.objects.filter(function=function).exists()
    assert function.default_size_id is None
    assert any("16x128" in m and "not registered" in m for m in _messages(request))


@pytest.mark.django_db
@override_settings(DEFAULT_FUNCTION_SIZE="m", DEFAULT_FUNCTION_SIZE_PROFILE="16x128")
def test_save_related_does_not_seed_when_sizes_are_declared():
    """An operator who declared sizes inline must not get an extra seeded 'm' size."""
    _profile("16x128")
    function = _function()
    profile = _profile("8x32")
    _size(function, "s", profile)
    request = _request_with_messages()

    _save_related(ProgramAdmin(Program, AdminSite()), request, function)

    function.refresh_from_db()
    names = sorted(FunctionSize.objects.filter(function=function).values_list("function_size", flat=True))
    assert names == ["s"]
    assert function.default_size_id is None


@pytest.mark.django_db
@override_settings(DEFAULT_FUNCTION_SIZE="m", DEFAULT_FUNCTION_SIZE_PROFILE="16x128")
def test_save_related_does_not_clobber_an_existing_default():
    """Editing a function that already has a default size leaves it and the catalog alone."""
    _profile("16x128")
    function = _function()
    profile = _profile("8x32")
    small = _size(function, "s", profile)
    function.default_size = small
    function.save(update_fields=["default_size"])
    request = _request_with_messages()

    _save_related(ProgramAdmin(Program, AdminSite()), request, function, change=True)

    function.refresh_from_db()
    assert function.default_size_id == small.id
    assert FunctionSize.objects.filter(function=function).count() == 1


@pytest.mark.django_db
@override_settings(DEFAULT_FUNCTION_SIZE="m", DEFAULT_FUNCTION_SIZE_PROFILE="16x128")
def test_save_related_ignores_ray_functions():
    """A Ray function is never seeded."""
    _profile("16x128")
    user = User.objects.create_user(username="ray-u", password="x")
    function = Program.objects.create(title="ray-fn", author=user, runner=Program.RAY)
    request = _request_with_messages()

    _save_related(ProgramAdmin(Program, AdminSite()), request, function)

    assert not FunctionSize.objects.filter(function=function).exists()
    assert function.default_size_id is None


def _program_add_post(author, **overrides) -> dict:
    """A minimal POST body for the Program add page, including the empty inline formsets.

    The size inline and the two m2m 'through' inlines each need their management form even when no
    rows are added, or the admin rejects the whole submission before our clean() runs.
    """
    data = {
        "title": "adminfn",
        "type": Program.GENERIC,
        "disabled_message": Program.DEFAULT_DISABLED_MESSAGE,
        "runner": Program.FLEETS,
        "entrypoint": "main.py",
        "env_vars": "{}",
        "dependencies": "[]",
        "arguments_schema": "{}",
        "author": str(author.pk),
        "function_sizes-TOTAL_FORMS": "0",
        "function_sizes-INITIAL_FORMS": "0",
        "function_sizes-MIN_NUM_FORMS": "0",
        "function_sizes-MAX_NUM_FORMS": "1000",
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
@override_settings(CE_DEFAULT_PROJECT_NAME="")
def test_add_page_blocks_a_fleets_function_with_no_ce_project(client):
    """End-to-end through the real add form: a providerless Fleets function with no assignable
    project is rejected inline and never persisted."""
    admin = User.objects.create_superuser(username="admin", password="x", email="a@b.c")
    client.force_login(admin)

    response = client.post(reverse("admin:api_program_add"), data=_program_add_post(admin), follow=False)

    assert response.status_code == 200  # re-rendered form, not a redirect
    assert "No active Code Engine project available" in response.content.decode()
    assert not Program.objects.filter(title="adminfn").exists()


@pytest.mark.django_db
@override_settings(
    CE_DEFAULT_PROJECT_NAME="default-proj", DEFAULT_FUNCTION_SIZE="m", DEFAULT_FUNCTION_SIZE_PROFILE="16x128"
)
def test_add_page_creates_a_runnable_fleets_function(client):
    """End-to-end: with a default CE project and default profile registered, the add form creates a
    Fleets function that gets both a CE project and a seeded default size."""
    _ce_project("default-proj")
    _profile("16x128")
    admin = User.objects.create_superuser(username="admin", password="x", email="a@b.c")
    client.force_login(admin)

    response = client.post(reverse("admin:api_program_add"), data=_program_add_post(admin), follow=False)

    assert response.status_code == 302  # saved, redirected to changelist
    function = Program.objects.get(title="adminfn")
    assert function.code_engine_project.project_name == "default-proj"
    assert function.default_size is not None
    assert function.default_size.function_size == "m"
