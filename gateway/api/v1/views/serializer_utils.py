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
    Compute profile fields exposed to users.

    ``name`` is deliberately omitted: the compute-profile name is internal and must not
    surface (here, or nested in a job/run response).
    """

    class Meta:
        model = ComputeProfile
        fields = [
            "compute_profile_id",
            "cpu",
            "gpu",
            "memory",
        ]
        ref_name = "ComputeProfileSerializer"
