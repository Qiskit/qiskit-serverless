"""
Serializers for V1 of the API.
"""

import json
import logging
import re
from typing import Any

from django.conf import settings
from packaging.requirements import Requirement, InvalidRequirement
from packaging.version import Version, InvalidVersion
from rest_framework import serializers as drf_serializers
from rest_framework import validators as validators_module
from rest_framework.serializers import ValidationError

from api.utils import check_whitelisted, sanitize_name
from core.models import Job, JobConfig, Program, Provider, RuntimeJob

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


class UploadProgramSerializer(drf_serializers.ModelSerializer):
    """
    Program serializer for the /upload end-point.
    """

    entrypoint = drf_serializers.CharField(required=False)
    image = drf_serializers.CharField(required=False)
    provider = drf_serializers.CharField(required=False)
    runner = drf_serializers.CharField(required=False)

    class Meta:
        model = Program
        fields = [
            "title",
            "entrypoint",
            "artifact",
            "dependencies",
            "env_vars",
            "image",
            "provider",
            "description",
            "type",
            "version",
            "runner",
        ]

    def get_validators(self):
        """Exclude UniqueConstraint validators.
        Uniqueness is enforced at DB level; the upload view handles
        upsert logic (find-or-create) before saving."""
        return [v for v in super().get_validators() if not isinstance(v, validators_module.UniqueTogetherValidator)]

    def validate_title(self, value):
        """Sanitize title to remove characters invalid for function names."""
        return sanitize_name(value)

    def validate_provider(self, value):
        """Sanitize provider name."""
        return sanitize_name(value) if value else value

    def validate_image(self, value):
        """Validates image."""
        return value

    def _parse_dependency(self, dep: Any):
        if not isinstance(dep, dict) and not isinstance(dep, str):
            raise ValidationError("'dependencies' should be an array with strings or dict.")

        if isinstance(dep, str):
            dep_string = dep
        else:
            dep_name = list(dep.keys())
            if len(dep_name) > 1 or len(dep_name) == 0:
                raise ValidationError("'dependencies' should be an array with dict containing one dependency only.")
            dep_name = str(dep_name[0])
            dep_version = str(list(dep.values())[0])

            try:
                if int(dep_version[0]) >= 0:
                    dep_version = f"=={dep_version}"
            except ValueError:
                pass

            dep_string = dep_name + dep_version

        requirement = Requirement(dep_string)
        req_specifier_list = list(requirement.specifier)
        req_specifier_first = next(iter(req_specifier_list), None)

        if len(req_specifier_list) > 1 or (req_specifier_first and req_specifier_first.operator != "=="):
            raise ValidationError("'dependencies' needs one fixed version using the '==' operator.")

        return requirement

    def _validate_deps(self, deps):
        if not isinstance(deps, list):
            raise ValidationError("'dependencies' should be an array.")

        if len(deps) == 0:
            return

        try:
            required_deps = [self._parse_dependency(dep) for dep in deps]
        except InvalidRequirement as invalid_requirement:
            raise ValidationError("Error while parsing dependencies.") from invalid_requirement

        try:
            check_whitelisted(required_deps)
        except ValueError as value_error:
            raise ValidationError(value_error.args[0]) from value_error

    def validate(self, attrs):  # pylint: disable=too-many-branches
        """Validates serializer data."""
        entrypoint = attrs.get("entrypoint", None)
        image = attrs.get("image", None)
        if entrypoint is None and image is None:
            raise ValidationError("At least one of attributes (entrypoint, image) is required.")
        try:
            deps = json.loads(attrs.get("dependencies", "[]"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValidationError(
                "'dependencies' should be an array of strings or objects: "
                "`['pendulum==3.0.0', '...'] or [{'pendulum':'3.0.0'}, {...}]`"
            ) from exc

        self._validate_deps(deps)

        title = attrs.get("title")
        provider = attrs.get("provider", None)
        if provider and "/" in title:
            raise ValidationError("Provider defined in title and in provider fields.")

        title_split = title.split("/")
        if len(title_split) > 2:
            raise ValidationError("Qiskit Function title is malformed. It can only contain one slash.")

        if image is not None:
            if provider is None and len(title_split) != 2:
                raise ValidationError("Custom images are only available if you are a provider.")
            if not provider:
                provider = title_split[0]
            provider_instance = Provider.objects.filter(name=provider).first()
            if provider_instance is None:
                raise ValidationError(f"{provider} is not valid provider.")
            if provider_instance.registry and not image.startswith(provider_instance.registry):
                raise ValidationError(f"Custom images must be in {provider_instance.registry}.")

        version = attrs.get("version", None)
        if version is not None:
            try:
                Version(version)
            except InvalidVersion as exc:
                raise ValidationError("Invalid version - expected format x.y.z") from exc

        return super().validate(attrs)


class RunProgramSerializer(drf_serializers.Serializer):  # pylint: disable=abstract-method
    """
    Program serializer for the /run end-point.
    """

    title = drf_serializers.CharField(max_length=255)
    arguments = drf_serializers.CharField()
    config = drf_serializers.JSONField()
    provider = drf_serializers.CharField(required=False, allow_null=True)
    compute_profile = drf_serializers.CharField(required=False, allow_null=True)

    _COMPUTE_PROFILE_RE = re.compile(r"^[a-z]+\d+[a-z]?-\d+x\d+(?:x\d+[a-z0-9]+)?$")

    def validate_title(self, value):
        """Sanitize title to remove characters invalid for function names."""
        return sanitize_name(value)

    def validate_provider(self, value):
        """Sanitize provider name."""
        return sanitize_name(value) if value else value

    def validate_compute_profile(self, value):
        """Validate compute profile format (e.g. 'cx3d-4x16' or 'gx3d-24x120x1a100p')."""
        if value and not self._COMPUTE_PROFILE_RE.match(value):
            raise drf_serializers.ValidationError(
                f"Invalid compute profile format: '{value}'. "
                f"Expected format: [type]-[cpu]x[memory] or [type]-[cpu]x[memory]x[gpu_count][gpu_type] "
                f"(lowercase only, e.g., 'cx3d-4x16' or 'gx3d-24x120x1a100p')"
            )
        return value


class JobConfigSerializer(drf_serializers.ModelSerializer):
    """
    JobConfig serializer first version. Include basic fields from the initial model.
    """

    class Meta:
        model = JobConfig
        fields = ["workers", "min_workers", "max_workers", "auto_scaling"]

    workers = drf_serializers.IntegerField(
        max_value=settings.RAY_CLUSTER_WORKER_REPLICAS_MAX,
        required=False,
        allow_null=True,
    )
    min_workers = drf_serializers.IntegerField(
        max_value=settings.RAY_CLUSTER_WORKER_MIN_REPLICAS_MAX,
        required=False,
        allow_null=True,
    )
    max_workers = drf_serializers.IntegerField(
        max_value=settings.RAY_CLUSTER_WORKER_MAX_REPLICAS_MAX,
        required=False,
        allow_null=True,
    )
    auto_scaling = drf_serializers.BooleanField(default=False, required=False, allow_null=True)


class RunJobSerializer(drf_serializers.ModelSerializer):
    """
    RunJobSerializer is used by the /run end-point.
    """

    compute_profile = drf_serializers.CharField(required=False, allow_null=True, allow_blank=True, default=None)

    class Meta:
        model = Job
        fields = ["id", "result", "status", "program", "created", "arguments", "compute_profile"]


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
