"""Admin module."""

import json
import logging

from django.contrib import admin
from django.utils.safestring import mark_safe
from django.utils.html import format_html
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
from core.services.storage.job_file_explorer import JobFileExplorer

logger = logging.getLogger("gateway.admin")


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


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    """JobAdmin."""

    search_fields = ["id", "author__username", "program__title"]
    list_filter = ["status"]
    exclude = ["arguments", "env_vars", "logs", "result"]
    ordering = ["-created"]
    inlines = [JobEventInline]
    autocomplete_fields = ["author", "program", "compute_resource", "config"]
    readonly_fields = ["storage_files_link"]

    fieldsets = [
        (
            None,
            {
                "fields": [
                    "author",
                    "program",
                    "status",
                    "sub_status",
                    "runner",
                    "fleet_id",
                    "ray_job_id",
                    "compute_resource",
                    "compute_profile",
                    "config",
                    "trial",
                    "business_model",
                ]
            },
        ),
        (
            "Storage",
            {
                "fields": ["storage_files_link"],
            },
        ),
    ]

    def get_urls(self):
        custom_urls = [
            path(
                "<uuid:job_id>/files/",
                self.admin_site.admin_view(self.job_files_view),
                name="job_files_view",
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
        except Exception as exc:
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

    @admin.display(description="Storage")
    def storage_files_link(self, obj):
        url = f"/admin/api/job/{obj.id}/files/"
        return format_html('<a href="{}" target="_blank">Ver ficheros de storage</a>', url)

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
