"""Admin module."""

from django.contrib import admin
from django.urls import path
from django.shortcuts import render, get_object_or_404
from django.contrib.admin.views.main import PAGE_VAR
from api.models import (
    GroupMetadata,
    JobConfig,
    Provider,
    Program,
    ProgramHistory,
    ComputeResource,
    Job,
    RuntimeJob,
)


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

        history_entries_list = ProgramHistory.objects.filter(program=program).order_by(
            "-changed"
        )

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


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    """JobAdmin."""

    search_fields = ["id", "author__username", "program__title"]
    list_filter = ["status"]
    exclude = ["arguments", "env_vars", "logs", "result"]
    ordering = ["-created"]


@admin.register(RuntimeJob)
class RuntimeJobAdmin(admin.ModelAdmin):
    """RuntimeJobAdmin."""

    search_fields = ["job__id"]


@admin.register(GroupMetadata)
class GroupMetadataAdmin(admin.ModelAdmin):
    """RuntimeJobAdmin."""

    search_fields = ["account", "group__name"]
