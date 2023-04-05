"""Admin module."""

from django.contrib import admin
from .models import Job, QuantumFunction, ComputeResource


@admin.register(QuantumFunction)
class ProgramAdmin(admin.ModelAdmin):
    """ProgramAdmin."""


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    """JobAdmin."""


@admin.register(ComputeResource)
class ComputeResourceAdmin(admin.ModelAdmin):
    """ComputeResourceAdmin."""
