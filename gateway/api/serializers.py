"""
Django Rest framework serializers for api application:
    - ProgramSerializer
    - JobSerializer

Version serializers inherit from the different serializers.
"""

from typing import Tuple, Union

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

    def get_provider_name_and_title(self, request_provider, title) -> Tuple[Union[str, None], str]:
        """
        This method returns provider_name and title from a title with / if it contains it
        """
        if request_provider:
            return request_provider, title

        # Check if title contains the provider: <provider>/<title>

        title_split = title.split("/")
        if len(title_split) == 1:
            return None, title_split[0]

        return title_split[0], title_split[1]

    def retrieve_private_function(self, title, author):
        """
        This method returns a Program entry searching by the title and author, if not None
        """
        return Program.objects.filter(title=title, author=author).first()

    def retrieve_provider_function(self, title, provider_name):
        """
        This method returns a Program entry searching by the title and provider, if not None
        """
        return Program.objects.filter(title=title, provider__name=provider_name).first()


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
        fields = "__all__"


class JobSerializerWithoutResult(serializers.ModelSerializer):
    """
    Serializer for the job model.
    """

    class Meta:
        model = Job
        fields = "__all__"


class RunProgramSerializer(serializers.Serializer):
    """
    Program serializer for the /run end-point
    """

    title = serializers.CharField(max_length=255)
    arguments = serializers.CharField()
    config = serializers.JSONField()
    provider = serializers.CharField(required=False, allow_null=True)
    compute_profile = serializers.CharField(required=False, allow_null=True)

    def retrieve_one_by_title(self, title, author):
        """
        This method returns a Program entry if it finds an entry searching by the title, if not None
        """
        return Program.objects.filter(title=title, author=author).order_by("-created").first()

    def update(self, instance, validated_data):
        pass

    def create(self, validated_data):
        pass


class RunJobSerializer(serializers.ModelSerializer):
    """
    Job serializer for the /run and end-point.

    Supports compute_profile parameter for specifying Code Engine Fleets machine profiles.
    Only used when runner=Fleets (code_engine_project is set).
    """

    compute_profile = serializers.CharField(required=False, allow_null=True, allow_blank=True, default=None)

    class Meta:
        model = Job
        fields = ["id", "status", "created", "compute_profile", "fleet_id", "arguments", "program"]


class RuntimeJobSerializer(serializers.ModelSerializer):
    """
    Serializer for the runtime job model.
    """

    class Meta:
        model = RuntimeJob
        # This is needed even if overidden in the v1 implementation
        fields = ["runtime_job", "runtime_session"]
