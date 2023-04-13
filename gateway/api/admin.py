"""Admin module."""

from django.contrib import admin
from .models import Job, Program, ComputeResource


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    """ProgramAdmin."""


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    """JobAdmin."""


@admin.register(ComputeResource)
class ComputeResourceAdmin(admin.ModelAdmin):
    """ComputeResourceAdmin."""
