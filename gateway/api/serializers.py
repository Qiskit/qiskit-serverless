"""
Django Rest framework serializers for api application:
    - ProgramSerializer
    - JobSerializer

Version serializers inherit from the different serializers.
"""

import json
import logging
from typing import Tuple, Union
from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.db.models import Q
from rest_framework import serializers
from api.services.arguments_storage import ArgumentsStorage

from api.repositories.functions import FunctionRepository
from api.repositories.users import UserRepository
from api.utils import build_env_variables, encrypt_env_vars, sanitize_name
from .models import (
    Provider,
    Program,
    Job,
    JobConfig,
    RuntimeJob,
    DEFAULT_PROGRAM_ENTRYPOINT,
    RUN_PROGRAM_PERMISSION,
)

logger = logging.getLogger("gateway.serializers")


class UploadProgramSerializer(serializers.ModelSerializer):
    """
    Program serializer for the /upload end-point
    """

    entrypoint = serializers.CharField(required=False)
    image = serializers.CharField(required=False)
    provider = serializers.CharField(required=False)

    class Meta:
        model = Program

    def _normalize_dependency(self, raw_dependency):
        if isinstance(raw_dependency, str):
            return raw_dependency

        dependency_name = list(raw_dependency.keys())[0]
        dependency_version = str(list(raw_dependency.values())[0])

        # if starts with a number then prefix ==
        try:
            if int(dependency_version[0]) >= 0:
                dependency_version = f"=={dependency_version}"
        except ValueError:
            logger.debug(
                "Dependency (%s) version (%s) does not starts with a number, "
                "assuming an operator (==, >=, ~=...) or empty",
                dependency_name,
                dependency_version,
            )

        return dependency_name + dependency_version

    def get_provider_name_and_title(
        self, request_provider, title
    ) -> Tuple[Union[str, None], str]:
        """
        This method returns provider_name and title from a title with / if it contains it
        """
        if request_provider:
            return request_provider, title

        # Check if title contains the provider: <provider>/<title>
        logger.debug("Provider is None, check if it is in the title.")

        title_split = title.split("/")
        if len(title_split) == 1:
            return None, title_split[0]

        return title_split[0], title_split[1]

    def check_provider_access(self, provider_name, author):
        """
        This method check if the author has access to the provider
        """
        provider = Provider.objects.filter(name=provider_name).first()
        if provider is None:
            logger.error("Provider [%s] does not exist.", provider_name)
            return False

        author_groups = author.groups.all()
        admin_groups = provider.admin_groups.all()
        has_access = any(group in admin_groups for group in author_groups)
        if not has_access:
            logger.error(
                "User [%s] has no access to provider [%s].", author.id, provider_name
            )

        return has_access

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

    def create(self, validated_data):
        title = sanitize_name(validated_data.get("title"))
        logger.info("Creating program [%s] with UploadProgramSerializer", title)

        provider_name = sanitize_name(validated_data.get("provider", None))
        if provider_name:
            validated_data["provider"] = Provider.objects.filter(
                name=provider_name
            ).first()

        env_vars = validated_data.get("env_vars")
        if env_vars:
            encrypted_env_vars = encrypt_env_vars(json.loads(env_vars))
            validated_data["env_vars"] = json.dumps(encrypted_env_vars)

        raw_dependencies = json.loads(validated_data.get("dependencies", "[]"))
        normalized_dependencies = [
            self._normalize_dependency(dep) for dep in raw_dependencies
        ]
        validated_data["dependencies"] = json.dumps(normalized_dependencies)

        return Program.objects.create(**validated_data)

    def update(self, instance, validated_data):
        logger.info(
            "Updating program [%s] with UploadProgramSerializer", instance.title
        )
        instance.entrypoint = validated_data.get(
            "entrypoint", DEFAULT_PROGRAM_ENTRYPOINT
        )
        raw_dependencies = json.loads(validated_data.get("dependencies", "[]"))
        normalized_dependencies = [
            self._normalize_dependency(dep) for dep in raw_dependencies
        ]
        instance.dependencies = json.dumps(normalized_dependencies)
        instance.env_vars = validated_data.get("env_vars", {})
        instance.artifact = validated_data.get("artifact")
        instance.author = validated_data.get("author")
        instance.image = validated_data.get("image")

        description = validated_data.get("description")
        if description is not None:
            instance.description = description

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
    Job serializer for the /run and end-point
    """

    class Meta:
        model = Job

    def is_trial(self, function: Program, author) -> bool:
        """
        This method checks if a group with run permissions from the author
            is assigned to a trial instance in a function
        """

        function_repository = FunctionRepository()
        user_repository = UserRepository()

        trial_groups = function_repository.get_trial_instances(function=function)
        user_run_groups = user_repository.get_groups_by_permissions(
            user=author, permission_name=RUN_PROGRAM_PERMISSION
        )

        return any(group in trial_groups for group in user_run_groups)

    def create(self, validated_data):
        logger.info("Creating Job with RunExistingJobSerializer")
        status = Job.QUEUED
        program = validated_data.get("program")
        arguments = validated_data.get("arguments", "{}")
        author = validated_data.get("author")
        config = validated_data.get("config", None)

        channel = validated_data.pop("channel")
        token = validated_data.pop("token")
        instance = validated_data.pop("instance", None)
        carrier = validated_data.pop("carrier")

        trial = self.is_trial(program, author)
        job = Job(
            trial=trial,
            status=status,
            program=program,
            arguments=arguments,
            author=author,
            config=config,
        )

        env = encrypt_env_vars(
            build_env_variables(
                channel=channel,
                token=token,
                job=job,
                trial_mode=trial,
                instance=instance,
            )
        )

        arguments_storage = ArgumentsStorage(author.username)
        arguments_storage.save(job.id, arguments)

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


class CatalogProviderSerializer(serializers.ModelSerializer):
    """
    Serializer for the Provider model in the Catalog View.
    """

    class Meta:
        model = Provider


class ListCatalogSerializer(serializers.ModelSerializer):
    """
    List Serializer for the Catalog View.
    """

    provider = CatalogProviderSerializer()
    available = serializers.SerializerMethodField()

    class Meta:
        model = Program

    def get_available(self, obj):
        """
        This method populates available field.
        If the user has RUN PERMISSION in any of its groups
        available field will be True. If not, will be False.
        """
        user = self.context.get("user", None)

        if user is None:
            logger.debug(
                "User not authenticated in ListCatalogSerializer return available to False"
            )
            return False

        # This will be refactorize it when we implement repository architecture
        # pylint: disable=duplicate-code
        run_program_permission = Permission.objects.get(codename=RUN_PROGRAM_PERMISSION)

        user_criteria = Q(user=user)
        run_permission_criteria = Q(permissions=run_program_permission)
        user_groups_with_run_permissions = Group.objects.filter(
            user_criteria & run_permission_criteria
        )

        return obj.instances.filter(
            id__in=[group.id for group in user_groups_with_run_permissions]
        ).exists()


class RetrieveCatalogSerializer(serializers.ModelSerializer):
    """
    Retrieve Serializer for the Catalog View.
    """

    provider = CatalogProviderSerializer()
    available = serializers.SerializerMethodField()

    class Meta:
        model = Program

    def to_representation(self, instance):
        representation = super().to_representation(instance)

        json_additional_info = {}
        if instance.additional_info is not None:
            try:
                json_additional_info = json.loads(instance.additional_info)
            except json.decoder.JSONDecodeError:
                logger.error("JSONDecodeError loading instance.additional_info")

        representation["additional_info"] = json_additional_info
        return representation

    def get_available(self, obj):
        """
        This method populates available field.
        If the user has RUN PERMISSION in any of its groups
        available field will be True. If not, will be False.
        """
        user = self.context.get("user", None)

        if user is None:
            logger.debug(
                "User not authenticated in ListCatalogSerializer return available to False"
            )
            return False

        # This will be refactorize it when we implement repository architecture
        # pylint: disable=duplicate-code
        run_program_permission = Permission.objects.get(codename=RUN_PROGRAM_PERMISSION)

        user_criteria = Q(user=user)
        run_permission_criteria = Q(permissions=run_program_permission)
        user_groups_with_run_permissions = Group.objects.filter(
            user_criteria & run_permission_criteria
        )

        return obj.instances.filter(
            id__in=[group.id for group in user_groups_with_run_permissions]
        ).exists()
