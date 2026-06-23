"""
Serializers for V1 of the API.
"""

import logging

from rest_framework import serializers as drf_serializers

from core.models import Job, Program, RuntimeJob

logger = logging.getLogger("api.api.v1.serializers")


class ProgramSerializer(drf_serializers.ModelSerializer):
    """
    Program serializer first version. Include basic fields from the initial model.
    """

    provider = drf_serializers.CharField(source="provider.name", read_only=True)

    class Meta:
        model = Program
        fields = [
            "id",
            "title",
            "entrypoint",
            "artifact",
            "dependencies",
            "provider",
            "description",
            "documentation_url",
            "type",
            "version",
            "runner",
        ]


class ProgramSummarySerializer(drf_serializers.ModelSerializer):
    """
    Program serializer with summary fields for job listings.
    """

    provider = drf_serializers.CharField(source="provider.name", read_only=True)

    class Meta:
        model = Program
        fields = ["id", "title", "provider"]


class RuntimeJobSerializer(drf_serializers.ModelSerializer):
    """
    Runtime job serializer first version.
    """

    class Meta:
        model = RuntimeJob
        fields = ["runtime_job", "runtime_session"]


class JobSerializer(drf_serializers.ModelSerializer):
    """
    Job serializer first version. Include basic fields from the initial model.
    """

    program = ProgramSerializer(many=False)

    class Meta:
        model = Job
        fields = [
            "id",
            "result",
            "status",
            "program",
            "created",
            "sub_status",
            "fleet_id",
            "compute_profile",
        ]


class JobSerializerWithoutResult(drf_serializers.ModelSerializer):
    """
    Job serializer first version. Include basic fields from the initial model.
    """

    program = ProgramSummarySerializer(many=False)

    class Meta:
        model = Job
        fields = ["id", "status", "program", "created", "sub_status", "fleet_id", "compute_profile"]
