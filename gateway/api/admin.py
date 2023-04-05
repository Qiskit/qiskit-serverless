"""Admin module."""

from django.contrib import admin
from .models import Job, QuantumFunction, ComputeResource


@admin.register(QuantumFunction)
class QuantumFunctionAdmin(admin.ModelAdmin):
    """QuantumFunctionAdmin."""


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    """JobAdmin."""


@admin.register(ComputeResource)
class ComputeResourceAdmin(admin.ModelAdmin):
    """ComputeResourceAdmin."""
