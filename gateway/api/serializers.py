"""
Django Rest framework serializers for api application:
    - ProgramSerializer
    - JobSerializer

Version serializers inherit from the different serializers.
"""

import json
import logging
from django.conf import settings
from rest_framework import serializers

from api.utils import build_env_variables, encrypt_env_vars
from .models import (
    Namespace,
    Program,
    Job,
    JobConfig,
    RuntimeJob,
    DEFAULT_PROGRAM_ENTRYPOINT,
)

logger = logging.getLogger("gateway.serializers")


class UploadProgramSerializer(serializers.ModelSerializer):
    """
    Program serializer for the /upload end-point
    """

    entrypoint = serializers.CharField(required=False)
    image = serializers.CharField(required=False)
    namespace = serializers.CharField(required=False)

    class Meta:
        model = Program

    def separate_namespace_from_title(self, title):
        """
        This method returns namespace and title from a title with /
        """
        title_split = title.split("/")
        if len(title_split) == 1:
            return None, title_split[0]
        return title_split[0], title_split[1]

    def check_namespace_access(self, namespace_name, author):
        """
        This method check if the author has access to the namespace
        """
        namespace = Namespace.objects.filter(name=namespace_name).first()
        if namespace is None:
            logger.error("Namespace [%s] does not exist.", namespace_name)
            return False
        logger.error(
            "User [%s] has no access to namespace [%s].", author.id, namespace_name
        )
        return namespace.admin in author.groups.all()

    def retrieve_private_function(self, title, author):
        """
        This method returns a Program entry searching by the title and author, if not None
        """
        return Program.objects.filter(title=title, author=author).first()

    def retrieve_namespace_function(self, title, namespace_name):
        """
        This method returns a Program entry searching by the title and namespace, if not None
        """
        namespace = Namespace.objects.filter(name=namespace_name).first()
        return Program.objects.filter(title=title, namespace=namespace).first()

    def create(self, validated_data):
        title = validated_data.get("title")
        logger.info("Creating program [%s] with UploadProgramSerializer", title)

        namespace_name = validated_data.get("namespace", None)
        if namespace_name:
            validated_data["namespace"] = Namespace.objects.filter(
                name=namespace_name
            ).first()

        env_vars = validated_data.get("env_vars")
        if env_vars:
            encrypted_env_vars = encrypt_env_vars(json.loads(env_vars))
            validated_data["env_vars"] = json.dumps(encrypted_env_vars)
        return Program.objects.create(**validated_data)

    def update(self, instance, validated_data):
        logger.info(
            "Updating program [%s] with UploadProgramSerializer", instance.title
        )
        instance.entrypoint = validated_data.get(
            "entrypoint", DEFAULT_PROGRAM_ENTRYPOINT
        )
        instance.dependencies = validated_data.get("dependencies", "[]")
        instance.env_vars = validated_data.get("env_vars", {})
        instance.artifact = validated_data.get("artifact")
        instance.author = validated_data.get("author")
        instance.image = validated_data.get("image")
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


class RunProgramSerializer(serializers.Serializer):
    """
    Program serializer for the /run end-point
    """

    title = serializers.CharField(max_length=255)
    arguments = serializers.CharField()
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

    def update(self, instance, validated_data):
        pass

    def create(self, validated_data):
        pass


class RunJobSerializer(serializers.ModelSerializer):
    """
    Job serializer for the /run and /run end-point
    """

    class Meta:
        model = Job

    def create(self, validated_data):
        logger.info("Creating Job with RunExistingJobSerializer")
        status = Job.QUEUED
        program = validated_data.get("program")
        arguments = validated_data.get("arguments", "{}")
        author = validated_data.get("author")
        config = validated_data.get("config", None)

        token = validated_data.pop("token")
        carrier = validated_data.pop("carrier")

        job = Job(
            status=status,
            program=program,
            arguments=arguments,
            author=author,
            config=config,
        )

        env = encrypt_env_vars(build_env_variables(token, job, arguments))
        try:
            env["traceparent"] = carrier["traceparent"]
        except KeyError:
            pass
        if program.env_vars:
            program_env = json.loads(program.env_vars)
            env.update(program_env)

        job.env_vars = json.dumps(env)
        job.save()

        return job


class RuntimeJobSerializer(serializers.ModelSerializer):
    """
    Serializer for the runtime job model.
    """

    class Meta:
        model = RuntimeJob
