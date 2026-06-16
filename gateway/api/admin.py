"""Admin module."""

import json

from django.contrib import admin
from django.db.models import Count, F, Q
from django.utils.safestring import mark_safe
from django.urls import path
from django.shortcuts import render, get_object_or_404
from django.contrib.admin.views.main import PAGE_VAR
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

    search_fields = ["name"]
    filter_horizontal = ["admin_groups"]


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    """ProgramAdmin."""

    search_fields = ["title", "author__username"]
    list_filter = ["provider", "type", "runner", "disabled"]
    exclude = ["env_vars"]
    filter_horizontal = ["instances", "trial_instances"]
    autocomplete_fields = ["author", "provider", "code_engine_project"]
    change_form_template = "program/change_form.html"

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

    def get_urls(self):
        """Add program history url to the available urls."""
        custom_urls = [
            path(
                "<path:object_id>/program-history/",
                self.admin_site.admin_view(self.program_history_view),
                name="program_history_view",
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

        return mark_safe(f'<pre class="event-json-block">{pretty_json}</pre>')

    @admin.display(description="Status/SubStatus")
    def pretty_status(self, instance):
        """Add a badge color per status type."""

        status = "None"
        if instance.event_type == JobEventType.STATUS_CHANGE:
            status = instance.data["status"]
        elif instance.event_type == JobEventType.SUB_STATUS_CHANGE:
            status = instance.data["sub_status"]

        return mark_safe(f'<span class="event-badge" data-event-status="{status}">{status}</span>')

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
    exclude = ["arguments", "env_vars", "logs", "result"]
    ordering = ["-created"]
    inlines = [JobEventInline]
    autocomplete_fields = ["author", "program", "compute_resource", "config"]

    class Media:
        js = ["admin/js/clickable_rows.js"]

    @admin.display(description="Status")
    def status_badge(self, obj):
        """Render status as a colored badge."""
        return mark_safe(f'<span class="qs-status-badge" data-status="{obj.status}">{obj.status}</span>')

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
