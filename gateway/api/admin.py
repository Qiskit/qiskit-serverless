"""Admin module."""

import json

from django.contrib import admin
from django.utils.safestring import mark_safe
from django.urls import path
from django.shortcuts import render, get_object_or_404
from django.contrib.admin.views.main import PAGE_VAR
from core.models import (
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


@admin.register(JobConfig)
class JobConfigAdmin(admin.ModelAdmin):
    """JobConfigAdmin."""


@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    """ProviderAdmin."""

    search_fields = ["name"]


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    """ProgramAdmin."""

    search_fields = ["title", "author__username"]
    list_filter = ["provider", "type", "disabled"]
    exclude = ["env_vars"]
    filter_horizontal = ["instances", "trial_instances"]
    change_form_template = "program/change_form.html"

    list_display = [
        "title",
        "provider",
        "author",
        "type",
        "disabled",
    ]

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


class JobEventInline(admin.TabularInline):
    """JobEventInline for admin views."""

    model = JobEvent
    extra = 0
    ordering = ("-created",)
    fields = ("event_type", "pretty_status", "created", "origin", "context", "render_data_json")
    readonly_fields = ("created", "pretty_status", "event_type", "origin", "context", "render_data_json")
    can_delete = False

    verbose_name_plural = "Job Events History"

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="Data JSON")
    def render_data_json(self, instance):
        """Formatea el campo JSON para que se vea como código."""
        if not instance.data:
            return ""

        pretty_json = json.dumps(instance.data, indent=2)

        return mark_safe(
            f'<pre style="background: #f4f4f4; padding: 5px; border-radius: 4px; '
            f'font-family: monospace; font-size: 11px; white-space: pre-wrap;">'
            f"{pretty_json.strip()}</pre>"
        )

    @admin.display(description="Status/SubStatus")
    def pretty_status(self, instance):
        """Añade un badge de color según el tipo de evento."""
        colors = {
            # STATUSES
            Job.QUEUED: "#f0ad4e",
            Job.PENDING: "#f0ad4e",
            Job.RUNNING: "#5bc0de",
            Job.SUCCEEDED: "#00aa00",
            Job.STOPPED: "#888888",
            Job.FAILED: "#cc0000",
            # SUB-STATUSES
            Job.MAPPING: "#5bc0de",
            Job.OPTIMIZING_HARDWARE: "#5bc0de",
            Job.WAITING_QPU: "#5bc0de",
            Job.EXECUTING_QPU: "#5bc0de",
            Job.POST_PROCESSING: "#5bc0de",
        }

        status = "None"
        if instance.event_type == JobEventType.STATUS_CHANGE:
            status = instance.data["status"]
        elif instance.event_type == JobEventType.SUB_STATUS_CHANGE:
            status = instance.data["sub_status"]

        # Buscamos el color, si no existe usamos gris por defecto
        color = colors.get(status, "#ff00ff")

        return mark_safe(
            f'<span style="background-color: {color} !important; color: white; padding: 3px 10px; '
            f'border-radius: 12px; font-weight: bold; font-size: 10px; text-transform: uppercase;">'
            f"{status}</span>"
        )


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    """JobAdmin."""

    search_fields = ["id", "author__username", "program__title"]
    list_filter = ["status"]
    exclude = ["arguments", "env_vars", "logs", "result"]
    ordering = ["-created"]
    inlines = [JobEventInline]

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


@admin.register(GroupMetadata)
class GroupMetadataAdmin(admin.ModelAdmin):
    """RuntimeJobAdmin."""

    search_fields = ["account", "group__name"]


@admin.register(JobEvent)
class JobEventAdmin(admin.ModelAdmin):
    """JobEventAdmin."""

    list_display = ("created", "job", "event_type", "origin", "context")
    date_hierarchy = "created"
