"""
Register the models for the admin panel.
"""

from django.contrib import admin
from .models import NestedProgram

admin.site.register(NestedProgram)
