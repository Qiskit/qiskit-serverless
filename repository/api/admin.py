"""
Register the models for the admin panel.
"""

from django.contrib import admin
from .models import NestedProgram


@admin.register(NestedProgram)
class NestedProgramAdmin(admin.ModelAdmin):
    """NestedProgramAdmin."""
