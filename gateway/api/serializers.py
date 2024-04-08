"""
Django Rest framework serializers for api application:
    - ProgramSerializer
    - JobSerializer

Version serializers inherit from the different serializers.
"""

from django.conf import settings
from rest_framework import serializers
from .models import Program, Job, JobConfig, RuntimeJob, CatalogEntry


class UploadProgramSerializer(serializers.ModelSerializer):
    """
    Program serializer for the /upload end-point
    """

    class Meta:
        model = Program

    def retrieve_one_by_title(self, title, author):
        """
        This method returns a Program entry if it finds an entry searching by the title, if not None
        """
        return (
            Program.objects.filter(title=title, author=author)
            .order_by("-created")
            .first()
        )

    def create(self, validated_data):
        return Program.objects.create(**validated_data)

    def update(self, instance, validated_data):
        instance.arguments = validated_data.get("arguments", "{}")
        instance.entrypoint = validated_data.get("entrypoint")
        instance.dependencies = validated_data.get("dependencies", "[]")
        instance.env_vars = validated_data.get("env_vars", "{}")
        instance.artifact = validated_data.get("artifact")
        instance.author = validated_data.get("author")
        instance.save()
        return instance


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
    auto_scaling = serializers.BooleanField(
        default=False, required=False, allow_null=True
    )
    python_version = serializers.ChoiceField(
        choices=(
            ("py39", "Version 3.9"),
            ("py310", "Version 3.10"),
        ),
        required=False,
        allow_null=True,
        allow_blank=True,
    )


class ProgramSerializer(serializers.ModelSerializer):
    """
    Serializer for the Program model.
    """

    class Meta:
        model = Program


class JobSerializer(serializers.ModelSerializer):
    """
    Serializer for the job model.
    """

    class Meta:
        model = Job


class ExistingProgramSerializer(serializers.Serializer):
    """Serializer for launching existing program."""

    title = serializers.CharField(max_length=255)
    arguments = serializers.CharField()

    def update(self, instance, validated_data):
        pass

    def create(self, validated_data):
        pass


class RuntimeJobSerializer(serializers.ModelSerializer):
    """
    Serializer for the runtime job model.
    """

    class Meta:
        model = RuntimeJob


class CatalogEntrySerializer(serializers.ModelSerializer):
    """
    Serializer for the catalog entry.
    """

    class Meta:
        model = CatalogEntry

        fields = ["id", "title", "description", "tags", "program", "status"]


class ToCatalogSerializer(serializers.ModelSerializer):
    """
    Serializer for the to catalog.
    """

    class Meta:
        model = CatalogEntry

        fields = ["id", "title", "description", "tags", "status"]
