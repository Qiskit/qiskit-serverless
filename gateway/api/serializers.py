"""
Django Rest framework serializers for api application:
    - ProgramSerializer
    - JobSerializer

Version serializers inherit from the different serializers.
"""

import json
from django.conf import settings
from rest_framework import serializers

from api.utils import build_env_variables, encrypt_env_vars
from .models import Program, Job, JobConfig, RuntimeJob, CatalogEntry


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
            ("py38", "Version 3.8"),
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


class RunExistingProgramSerializer(serializers.Serializer):
    """
    Program serializer for the /run_existing end-point
    """

    title = serializers.CharField(max_length=255)
    arguments = serializers.JSONField()
    config = serializers.JSONField()

    def retrieve_one_by_title(self, title, author):
        """
        This method returns a Program entry if it finds an entry searching by the title, if not None
        """
        return (
            Program.objects.filter(title=title, author=author)
            .order_by("-created")
            .first()
        )


class RunExistingJobSerializer(serializers.ModelSerializer):
    """
    Job serializer for the /run_existing end-point
    """

    arguments = serializers.JSONField()

    class Meta:
        model = Job
        fields = ["id", "result", "status", "program", "created", "arguments"]

    def create(self, validated_data):
        status = Job.QUEUED
        arguments = validated_data.get("arguments", "{}")
        token = validated_data.pop("token")
        carrier = validated_data.pop("carrier")

        job = Job(status=status, **validated_data)

        # env = encrypt_env_vars(build_env_variables(token, job, json.dumps(arguments)))
        env = encrypt_env_vars(build_env_variables(token, job, arguments))
        try:
            env["traceparent"] = carrier["traceparent"]
        except KeyError:
            pass

        job.env_vars = json.dumps(env)
        job.save()
        
        return job


class JobSerializer(serializers.ModelSerializer):
    """
    Serializer for the job model.
    """

    class Meta:
        model = Job


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
