"""
Register the models for the admin panel.
"""

from django.contrib import admin
from .models import QuantumFunction


@admin.register(QuantumFunction)
class NestedProgramAdmin(admin.ModelAdmin):
    """NestedProgramAdmin."""
