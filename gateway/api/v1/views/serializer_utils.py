"""
utilities for API.
"""

from rest_framework import serializers

from api.utils import sanitize_name
from core.models import ComputeProfile


class SanitizedCharField(serializers.CharField):
    """CharField that applies sanitize_name to its value."""

    def to_internal_value(self, data):
        """Method to sanitize the field"""
        value = super().to_internal_value(data)
        return sanitize_name(value) if value else None


class ComputeProfileSerializer(serializers.ModelSerializer):
    """
    Compute profile fields exposed for a job's `compute_profile_fk`.
    """

    class Meta:
        model = ComputeProfile
        fields = [
            "compute_profile_id",
            "name",
            "cpu",
            "gpu",
            "memory",
        ]
        ref_name = "ComputeProfileSerializer"
