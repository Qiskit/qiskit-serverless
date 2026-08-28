"""Admin module."""

import json
import logging

from django import forms
from django.contrib import admin, messages
from django.db.models import Count, F, Q
from django.utils.html import format_html
from django.urls import path
from django.shortcuts import render, get_object_or_404
from django.contrib.admin.views.main import PAGE_VAR

from api.domain.arguments_schema import (
    MAX_SCHEMA_LENGTH,
    UnsupportedSchemaError,
    check_uploaded_schema_in_isolation,
)
from api.domain.exceptions.invalid_arguments_exception import InvalidArgumentsException
from api.use_cases.programs.validate_arguments import validate_arguments
from core.models import (
    CodeEngineProject,
    Config,
    GroupMetadata,
    JobConfig,
    JobEvent,
    Provider,
    Program,
    ProgramHistory,
    ComputeResource,
    Job,
    RuntimeJob,
)
from core.model_managers.job_events import JobEventContext, JobEventOrigin, JobEventType
from core.services.storage.job_file_explorer import JobFileExplorer

logger = logging.getLogger("gateway.admin")


def get_dashboard_stats():
    """Return platform-wide stats for the admin dashboard."""
    total_jobs = Job.objects.count()

    status_rows = Job.objects.values("status").annotate(count=Count("id")).order_by("-count")
    jobs_by_status = [
        {
            "status": row["status"],
            "count": row["count"],
            "pct": round(row["count"] * 100 / total_jobs) if total_jobs else 0,
        }
        for row in status_rows
    ]

    provider_rows = Job.objects.values(name=F("program__provider__name")).annotate(count=Count("id")).order_by("-count")
    jobs_by_provider = [
        {
            "name": row["name"] or "Custom",
            "count": row["count"],
            "pct": round(row["count"] * 100 / total_jobs) if total_jobs else 0,
        }
        for row in provider_rows
    ]

    return {
        "providers_count": Provider.objects.count(),
        "providers_active": Provider.objects.filter(program__disabled=False).distinct().count(),
        "programs_count": Program.objects.count(),
        "programs_disabled": Program.objects.filter(disabled=True).count(),
        "jobs_count": total_jobs,
        "jobs_active": Job.objects.filter(status__in=Job.ACTIVE_STATUSES).count(),
        "ce_projects_count": CodeEngineProject.objects.count(),
        "ce_projects_active": CodeEngineProject.objects.filter(active=True).count(),
        "jobs_by_status": jobs_by_status,
        "jobs_by_provider": jobs_by_provider,
    }


@admin.register(JobConfig)
class JobConfigAdmin(admin.ModelAdmin):
    """JobConfigAdmin."""

    search_fields = ["id"]


@admin.register(CodeEngineProject)
class CodeEngineProjectAdmin(admin.ModelAdmin):
    """CodeEngineProjectAdmin."""

    search_fields = ["project_name", "project_id", "region"]
    list_display = ["project_name", "region"]


@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    """ProviderAdmin."""

    search_fields = ["name", "code_engine_project__project_name"]
    list_display = ["name", "code_engine_project"]
    filter_horizontal = ["admin_groups"]


def _arguments_schema_error(value: str | None) -> str | None:
    """Return why `value` is not a usable arguments schema, or None when it is.

    The wording matches the upload endpoint's serializer on purpose, so a schema turned down here
    and one turned down there read the same in the logs.
    """
    if not value:
        # The column allows null and defaults to "{}", so a blank field means the function does not
        # declare a schema. Django strips a form CharField, so spaces only arrive as "".
        return None

    if len(value) > MAX_SCHEMA_LENGTH:
        return f"arguments_schema is {len(value)} characters long and the maximum is {MAX_SCHEMA_LENGTH}."

    try:
        check_uploaded_schema_in_isolation(value)
    except UnsupportedSchemaError as exc:
        return f"arguments_schema cannot be used: {exc}."

    return None


class ProgramAdminForm(forms.ModelForm):
    """Program form that validates arguments_schema the way the upload endpoint does.

    Without this, the admin was the only way left to store a schema the gateway cannot evaluate, and
    a single bad row breaks `client.functions()` for everyone who can see that function, because the
    SDK decodes the whole list at once.
    """

    class Meta:
        model = Program
        # A ModelForm has to name fields or exclude, or Django raises ImproperlyConfigured when the
        # class is declared. ProgramAdmin narrows this down to its fieldsets anyway.
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stored_schema_error = None
        # Only when showing an existing row: a bound form is handling a submission, where the stored
        # value is no longer what the page is about, and an unsaved instance has nothing stored yet.
        if self.is_bound or not self.instance.pk:
            return

        self.stored_schema_error = _arguments_schema_error(self.instance.arguments_schema)
        if self.stored_schema_error is None:
            return

        field = self.fields["arguments_schema"]
        field.help_text = format_html(
            '<span style="color: var(--error-fg);">{}</span>{}',
            self.stored_schema_error,
            f" {field.help_text}" if field.help_text else "",
        )

    def clean_arguments_schema(self):
        """Check the schema, but only when this field is the one being changed.

        A function whose stored schema is already broken still has to be editable: disabling it is
        exactly what you want to be able to do quickly, and validating on every save would stand in
        the way.
        """
        value = self.cleaned_data["arguments_schema"]
        if "arguments_schema" not in self.changed_data:
            return value

        error = _arguments_schema_error(value)
        if error is not None:
            raise forms.ValidationError(error)

        return value


class ValidateArgumentsForm(forms.Form):
    """Arguments to try against a function's stored schema."""

    arguments = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 12, "cols": 80}),
        label="Arguments (JSON)",
        help_text="Leave empty to check what an empty argument list does.",
    )


def _format_arguments_path(error_path: list) -> str:
    """Render a validation path the way it would be written in the arguments document.

    `jsonschema` hands back the location of the failure as a list of property names and array
    indices. Written out, it is the part of the payload to go and look at; an empty list means the
    whole document failed, and the caller leaves it out.
    """
    parts: list[str] = []
    for segment in error_path:
        if isinstance(segment, int):
            parts.append(f"[{segment}]")
        else:
            parts.append(f".{segment}" if parts else str(segment))
    return "".join(parts)


def _validate_arguments_result(program: Program, arguments: str) -> dict:
    """Check `arguments` against `program`'s schema and describe the outcome for the page.

    Calls the same function the API calls, so the verdict here is the verdict a client would get,
    including the size limits and the isolated evaluation. That also means a schema that cannot be
    used comes back as a rejection with the reason, never as a server error.
    """
    try:
        validate_arguments(program, arguments)
    except InvalidArgumentsException as exc:
        return {"valid": False, "message": exc.message, "path": _format_arguments_path(exc.path)}

    return {"valid": True}


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    """ProgramAdmin."""

    form = ProgramAdminForm
    search_fields = ["title", "author__username"]
    list_filter = ["provider", "type", "runner", "disabled"]
    filter_horizontal = ["instances", "trial_instances"]
    autocomplete_fields = ["author", "provider", "code_engine_project"]
    change_form_template = "program/change_form.html"
    fieldsets = [
        (
            "Info",
            {
                "fields": [
                    "title",
                    "readable_title",
                    "type",
                    "description",
                    "version",
                    "documentation_url",
                    "additional_info",
                ]
            },
        ),
        ("Status", {"fields": ["disabled", "disabled_message"]}),
        (
            "Execution",
            {"fields": ["runner", "gpu", "entrypoint", "artifact", "image", "dependencies", "arguments_schema"]},
        ),
        ("Fleets", {"fields": ["code_engine_project"]}),
        ("Ownership", {"fields": ["author", "provider", "instances", "trial_instances"]}),
    ]

    list_display = [
        "title",
        "provider",
        "author",
        "type",
        "runner",
        "disabled",
    ]

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        if obj:
            readonly_fields.append("title")
        return readonly_fields

    def render_change_form(self, request, context, *args, **kwargs):
        """Warn at the top of the page when the stored arguments_schema is unusable.

        The form has already worked out the reason, so this costs nothing extra. It only fires on a
        page being shown, since `stored_schema_error` stays None for a bound form.

        The remaining arguments are passed straight through: Django's `_changeform_view` sends `add`,
        `change`, `form_url` and `obj` by keyword, and none of them matter here.
        """
        stored_schema_error = getattr(context["adminform"].form, "stored_schema_error", None)
        if stored_schema_error:
            messages.warning(request, stored_schema_error)

        return super().render_change_form(request, context, *args, **kwargs)

    def get_urls(self):
        """Add the program history and validate arguments urls to the available urls."""
        custom_urls = [
            path(
                "<path:object_id>/program-history/",
                self.admin_site.admin_view(self.program_history_view),
                name="program_history_view",
            ),
            path(
                "<path:object_id>/validate-arguments/",
                self.admin_site.admin_view(self.program_validate_arguments_view),
                name="program_validate_arguments_view",
            ),
        ]
        return custom_urls + super().get_urls()

    def program_history_view(self, request, object_id):
        """View to display the program history."""
        program = get_object_or_404(Program, pk=object_id)

        history_entries_list = ProgramHistory.objects.filter(program=program).order_by("-changed")

        paginator = self.get_paginator(request, history_entries_list, 100)
        page_number = request.GET.get(PAGE_VAR, 1)
        page_obj = paginator.get_page(page_number)
        page_range = paginator.get_elided_page_range(page_obj.number)

        context = {
            **self.admin_site.each_context(request),
            "object": program,
            "history_entries": page_obj,
            "page_range": page_range,
            "page_var": PAGE_VAR,
            "pagination_required": paginator.count > 100,
            "opts": self.model._meta,
            "app_label": self.model._meta.app_label,
        }

        return render(request, "program/program_history.html", context)

    def program_validate_arguments_view(self, request, object_id):
        """View to try arguments against the schema this function already has stored.

        Nothing is written: the page only reads the function to get its schema. Checking a schema
        used to mean going through the API with a token and an instance, which is a lot of setup for
        a question you are asking while looking at the function in the admin.
        """
        program = get_object_or_404(Program, pk=object_id)

        form = ValidateArgumentsForm(request.POST) if request.method == "POST" else ValidateArgumentsForm()
        result = _validate_arguments_result(program, form.cleaned_data["arguments"]) if form.is_valid() else None

        context = {
            **self.admin_site.each_context(request),
            "object": program,
            "form": form,
            "result": result,
            # An empty schema validates everything, which is the right answer but reads as a pass.
            # The page says so next to the verdict, and needs to know which case it is in.
            "has_schema": bool(program.arguments_schema) and program.arguments_schema != "{}",
            "opts": self.model._meta,
            "app_label": self.model._meta.app_label,
        }

        return render(request, "program/validate_arguments.html", context)


@admin.register(ComputeResource)
class ComputeResourceAdmin(admin.ModelAdmin):
    """ComputeResourceAdmin."""

    search_fields = ["title", "owner__username"]
    list_filter = ["active"]
    autocomplete_fields = ["owner"]


class JobEventInline(admin.TabularInline):
    """JobEventInline for admin views."""

    model = JobEvent
    extra = 0
    ordering = ("-created",)
    fields = ("created", "event_type", "pretty_status", "origin", "context", "render_data_json")
    readonly_fields = ("created", "pretty_status", "event_type", "origin", "context", "render_data_json")
    can_delete = False

    verbose_name_plural = "Job Events History"

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="Data JSON")
    def render_data_json(self, instance):
        """Format JSON field to visualize it like code."""
        if not instance.data:
            return ""

        pretty_json = json.dumps(instance.data, indent=2).strip()

        return format_html('<pre class="event-json-block">{}</pre>', pretty_json)

    @admin.display(description="Status/SubStatus")
    def pretty_status(self, instance):
        """Add a badge color per status type."""

        status = "None"
        if instance.event_type == JobEventType.STATUS_CHANGE:
            status = instance.data["status"]
        elif instance.event_type == JobEventType.SUB_STATUS_CHANGE:
            status = instance.data["sub_status"]

        return format_html('<span class="event-badge" data-event-status="{}">{}</span>', status, status)

    class Media:  # pylint: disable=too-few-public-methods
        """JobEventInline Media"""

        css = {"all": ["admin/css/admin_job_event_inline.css"]}


class JobProgramFilter(admin.SimpleListFilter):
    """Filter jobs by provider / program."""

    title = "Program"
    parameter_name = "job_program"

    def lookups(self, request, model_admin):
        qs = model_admin.get_queryset(request).select_related("program__provider")
        seen = set()
        choices = []
        has_custom = False
        for job in qs.only("program_id"):
            pid = job.program_id
            if pid is None:
                has_custom = True
                continue
            if pid in seen:
                continue
            seen.add(pid)
            program = Program.objects.select_related("provider").filter(pk=pid).first()
            if program is None or program.provider is None:
                has_custom = True
            else:
                choices.append((str(pid), f"{program.provider.name} / {program.title}"))
        choices.sort(key=lambda x: x[1])
        if has_custom:
            choices.insert(0, ("custom", "Custom"))
        return choices

    def queryset(self, request, queryset):
        if self.value() == "custom":
            return queryset.filter(Q(program__isnull=True) | Q(program__provider__isnull=True))
        if self.value():
            return queryset.filter(program_id=self.value())
        return queryset


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    """JobAdmin."""

    search_fields = ["id", "author__username", "program__title"]
    list_filter = ["status", "runner", JobProgramFilter]
    list_display = ["runner", "author", "get_program", "status_badge", "created", "updated"]
    list_select_related = ["author", "program", "program__provider"]
    ordering = ["-created"]
    inlines = []
    autocomplete_fields = ["author", "program", "compute_resource", "config"]
    change_form_template = "admin/api/job/change_form.html"
    fieldsets = [
        (
            "Info",
            {
                "fields": [
                    "program",
                    "author",
                    "runner",
                    "status",
                    "sub_status",
                    "running_started_at",
                    "trial",
                    "business_model",
                    "account_id",
                    "instance_crn",
                    "version",
                ]
            },
        ),
        (
            "Fleets",
            {
                "fields": [
                    "fleet_id",
                    "compute_profile",
                    "ce_project_name",
                    "ce_region",
                    "code_engine_project",
                ]
            },
        ),
        ("Ray", {"fields": ["ray_job_id", "compute_resource", "gpu", "config"]}),
    ]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        formfield = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if db_field.name == "program" and hasattr(formfield.widget, "can_delete_related"):
            formfield.widget.can_delete_related = False
        return formfield

    def get_urls(self):
        custom_urls = [
            path(
                "<path:job_id>/files/",
                self.admin_site.admin_view(self.job_files_view),
                name="job_files_view",
            ),
            path(
                "<path:job_id>/events/",
                self.admin_site.admin_view(self.job_events_view),
                name="job_events_view",
            ),
        ]
        return custom_urls + super().get_urls()

    def job_files_view(self, request, job_id):
        """Dedicated page listing all storage files for a job."""
        job = get_object_or_404(Job, pk=job_id)
        error = None
        groups = []
        try:
            groups = JobFileExplorer().explore(job)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error loading storage files for job %s: %s", job_id, exc, exc_info=True)
            error = str(exc)

        context = {
            **self.admin_site.each_context(request),
            "job": job,
            "groups": groups,
            "error": error,
            "opts": self.model._meta,
            "app_label": self.model._meta.app_label,
        }
        return render(request, "admin/api/job/files.html", context)

    def job_events_view(self, request, job_id):
        """Dedicated page listing all events for a job."""
        job = get_object_or_404(Job, pk=job_id)
        raw_events = job.job_events.all()
        events = []
        for event in raw_events:
            if event.event_type == JobEventType.STATUS_CHANGE:
                display_status = event.data.get("status", "")
            elif event.event_type == JobEventType.SUB_STATUS_CHANGE:
                display_status = event.data.get("sub_status", "")
            else:
                display_status = ""
            events.append(
                {
                    "obj": event,
                    "display_status": display_status,
                    "pretty_json": json.dumps(event.data, indent=2) if event.data else "",
                }
            )
        context = {
            **self.admin_site.each_context(request),
            "job": job,
            "events": events,
            "opts": self.model._meta,
            "app_label": self.model._meta.app_label,
        }
        return render(request, "admin/api/job/events.html", context)

    class Media:
        js = ["admin/js/clickable_rows.js"]

    @admin.display(description="Status")
    def status_badge(self, obj):
        """Render status as a colored badge."""
        return format_html('<span class="qs-status-badge" data-status="{}">{}</span>', obj.status, obj.status)

    @admin.display(description="Program")
    def get_program(self, obj):
        """Return provider / program label for list display."""
        if obj.program is None:
            return "-"
        provider = obj.program.provider
        if provider:
            return f"{provider.name} / {obj.program.title}"
        return obj.program.title

    def save_model(self, request, obj, form, change):
        if change:
            if "status" in form.changed_data:
                JobEvent.objects.add_status_event(
                    job_id=obj.id,
                    origin=JobEventOrigin.BACKOFFICE,
                    context=JobEventContext.SAVE_MODEL,
                    status=obj.status,
                )

            if "sub_status" in form.changed_data:
                JobEvent.objects.add_sub_status_event(
                    job_id=obj.id,
                    origin=JobEventOrigin.BACKOFFICE,
                    context=JobEventContext.SAVE_MODEL,
                    sub_status=obj.sub_status,
                )

        super().save_model(request, obj, form, change)


@admin.register(RuntimeJob)
class RuntimeJobAdmin(admin.ModelAdmin):
    """RuntimeJobAdmin."""

    search_fields = ["job__id"]
    autocomplete_fields = ["job"]


@admin.register(GroupMetadata)
class GroupMetadataAdmin(admin.ModelAdmin):
    """GroupMetadataAdmin."""

    search_fields = ["account", "group__name"]
    autocomplete_fields = ["group"]


@admin.register(Config)
class ConfigAdmin(admin.ModelAdmin):
    """ConfigAdmin."""

    list_display = ["name", "value", "bool_value", "description", "updated"]
    search_fields = ["name", "value", "description"]
    ordering = ["name"]
    readonly_fields = ["created", "updated"]

    @admin.display(description="Bool value", boolean=True)
    def bool_value(self, obj):
        """Display the boolean interpretation of the value."""
        return obj.value.lower() == "true"


@admin.register(JobEvent)
class JobEventAdmin(admin.ModelAdmin):
    """JobEventAdmin."""

    list_display = ("created", "job", "event_type", "origin", "context")
    date_hierarchy = "created"


class QiskitAdminSite(admin.AdminSite):
    """AdminSite subclass that injects dashboard stats into the index view."""

    def index(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["dashboard_stats"] = get_dashboard_stats()
        return super().index(request, extra_context)


# Swap the class of the default site so all existing registrations are kept
# (including django.contrib.auth models registered by Django itself).
admin.site.__class__ = QiskitAdminSite
