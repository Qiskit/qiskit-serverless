"""
Django Rest framework serializers for api application:
    - ProgramSerializer
    - JobSerializer

Version serializers inherit from the different serializers.
"""

from django.conf import settings
from rest_framework import serializers
from rest_framework import validators as validators_module

from core.models import (
    Program,
    Job,
    JobConfig,
    RuntimeJob,
)


class UploadProgramSerializer(serializers.ModelSerializer):
    """
    Program serializer for the /upload end-point
    """

    entrypoint = serializers.CharField(required=False)
    image = serializers.CharField(required=False)
    provider = serializers.CharField(required=False)
    runner = serializers.CharField(required=False)

    class Meta:
        model = Program
        fields = [
            "title",
            "description",
            "version",
            "entrypoint",
            "artifact",
            "image",
            "env_vars",
            "dependencies",
            "runner",
        ]

    def get_validators(self):
        """Exclude UniqueConstraint validators.
        Uniqueness is enforced at DB level; the upload view handles
        upsert logic (find-or-create) before saving."""
        return [v for v in super().get_validators() if not isinstance(v, validators_module.UniqueTogetherValidator)]


class JobConfigSerializer(serializers.ModelSerializer):
    """
    Serializer for the Job Config model.
    """

    class Meta:
        model = JobConfig

    workers = serializers.IntegerField(
        max_value=settings.RAY_CLUSTER_WORKER_REPLICAS_MAX,
        required=False,
        allow_null=True,
    )
    min_workers = serializers.IntegerField(
        max_value=settings.RAY_CLUSTER_WORKER_MIN_REPLICAS_MAX,
        required=False,
        allow_null=True,
    )
    max_workers = serializers.IntegerField(
        max_value=settings.RAY_CLUSTER_WORKER_MAX_REPLICAS_MAX,
        required=False,
        allow_null=True,
    )
    auto_scaling = serializers.BooleanField(default=False, required=False, allow_null=True)


class ProgramSerializer(serializers.ModelSerializer):
    """
    Serializer for the Program model.
    """

    provider = serializers.CharField(source="provider.name", read_only=True)

    class Meta:
        model = Program


class JobSerializer(serializers.ModelSerializer):
    """
    Serializer for the job model.
    """

    class Meta:
        model = Job


class JobSerializerWithoutResult(serializers.ModelSerializer):
    """
    Serializer for the job model.
    """

    class Meta:
        model = Job


class RunProgramSerializer(serializers.Serializer):
    """
    Program serializer for the /run end-point
    """

    title = serializers.CharField(max_length=255)
    arguments = serializers.CharField()
    config = serializers.JSONField()
    provider = serializers.CharField(required=False, allow_null=True)
    compute_profile = serializers.CharField(required=False, allow_null=True)


class RuntimeJobSerializer(serializers.ModelSerializer):
    """
    Serializer for the runtime job model.
    """

    class Meta:
        model = RuntimeJob
        # This is needed even if overidden in the v1 implementation
        fields = ["runtime_job", "runtime_session"]
