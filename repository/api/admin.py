"""
Register the models for the admin panel.
"""

from django.contrib import admin
from .models import Program


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    """ProgramAdmin."""
