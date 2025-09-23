"""
utilities for API.
"""

from rest_framework import serializers

from api.utils import sanitize_name


class SanitizedCharField(serializers.CharField):
    """CharField that applies sanitize_name to its value."""

    def to_internal_value(self, data):
        """Method to sanitize the field"""
        value = super().to_internal_value(data)
        return sanitize_name(value) if value else None
