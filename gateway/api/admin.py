"""Admin module."""

from django.contrib import admin
from django.urls import path
from django.shortcuts import render, get_object_or_404
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
        program = get_object_or_404(Program, pk=object_id)

        history_entries = ProgramHistory.objects.filter(program=program).order_by(
            "-changed"
        )

        context = {
            **self.admin_site.each_context(request),
            "object": program,
            "history_entries": history_entries,
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

    search_fields = ["account"]
