"""
Serializers api for V1.
"""

import json
import logging
import re
from typing import Any

from packaging.requirements import Requirement, InvalidRequirement
from packaging.version import Version, InvalidVersion
from rest_framework.serializers import ValidationError

from api import serializers
from api.utils import check_whitelisted
from core.models import Provider

logger = logging.getLogger("api.api.v1.serializers")

# Strict OCI/Docker image reference grammar:
#   [registry[:port]/]repository[:tag][@digest]
# This rejects shell metacharacters, whitespace and otherwise malformed
# references before they ever reach the runner / orchestration objects.
IMAGE_REFERENCE_RE = re.compile(
    r"^"
    r"(?:(?P<registry>[a-z0-9]+(?:[.-][a-z0-9]+)*(?::[0-9]+)?)/)?"  # optional registry host[:port]/
    r"(?P<repo>[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*)"  # repository path
    r"(?::(?P<tag>[A-Za-z0-9_][A-Za-z0-9._-]{0,127}))?"  # optional tag
    r"(?:@(?P<digest>[A-Za-z0-9]+:[A-Fa-f0-9]{32,}))?"  # optional digest
    r"$"
)


def _image_in_registry(image: str, registry: str) -> bool:
    """Return True only when ``image`` is hosted under ``registry``.

    Enforces a path boundary so that a registry of ``docker.io`` is NOT
    satisfied by ``docker.io.attacker.com/evil`` (the bug a bare
    ``str.startswith`` introduces).
    """
    registry = registry.rstrip("/")
    return image == registry or image.startswith(registry + "/")


class ProgramSerializer(serializers.ProgramSerializer):
    """
    Program serializer first version. Include basic fields from the initial model.
    """

    class Meta(serializers.ProgramSerializer.Meta):
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


class ProgramSummarySerializer(serializers.ProgramSerializer):
    """
    Program serializer with summary fields for job listings.
    """

    class Meta(serializers.ProgramSerializer.Meta):
        fields = ["id", "title", "provider"]


class UploadProgramSerializer(serializers.UploadProgramSerializer):
    """
    UploadProgramSerializer is used by the /upload end-point
    """

    def validate_entrypoint(self, value):
        """Validate the entrypoint is a safe, relative ``.py`` file path.

        The entrypoint is interpolated into the runner's execution command
        (e.g. ``python {entrypoint}`` for Ray) and into COS/PDS object paths, so
        it must not contain shell metacharacters, be absolute, or traverse
        outside the function directory via ``..``.
        """
        if value is None:
            return value
        segments = value.split("/")
        if (
            not isinstance(value, str)
            or not re.fullmatch(r"[A-Za-z0-9_./-]+\.py", value)
            or value.startswith("/")
            or ".." in segments
        ):
            raise ValidationError(
                "Invalid entrypoint. It must be a relative path to a .py file "
                "without '..' segments or shell characters."
            )
        return value

    def validate_image(self, value):
        """Validate that the image is a well-formed container reference."""
        if value is None:
            return value
        if not isinstance(value, str) or not IMAGE_REFERENCE_RE.match(value):
            raise ValidationError(
                "Invalid image reference. Expected format: "
                "[registry[:port]/]repository[:tag][@digest]."
            )
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

            # if starts with a number then prefix ==
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
            # validate dependencies
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
            if provider_instance.registry and not _image_in_registry(image, provider_instance.registry):
                raise ValidationError(f"Custom images must be in {provider_instance.registry}.")

        # Validate `version` using packaging.version (PEP 440 compatible)
        version = attrs.get("version", None)
        if version is not None:
            try:
                Version(version)
            except InvalidVersion as exc:
                raise ValidationError("Invalid version - expected format x.y.z") from exc

        return super().validate(attrs)

    class Meta(serializers.UploadProgramSerializer.Meta):
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


class RunProgramSerializer(serializers.RunProgramSerializer):
    """
    RunExistingProgramSerializer is used by the /run end-point
    """


class JobConfigSerializer(serializers.JobConfigSerializer):
    """
    JobConfig serializer first version. Include basic fields from the initial model.
    """

    class Meta(serializers.JobConfigSerializer.Meta):
        fields = [
            "workers",
            "min_workers",
            "max_workers",
            "auto_scaling",
        ]


class RunJobSerializer(serializers.RunJobSerializer):
    """
    RunJobSerializer is used by the /run end-point
    """

    class Meta(serializers.RunJobSerializer.Meta):
        fields = ["id", "result", "status", "program", "created", "arguments", "compute_profile"]


class RuntimeJobSerializer(serializers.RuntimeJobSerializer):
    """
    Runtime job serializer first version. Serializer for the runtime job model.
    """

    class Meta(serializers.RuntimeJobSerializer.Meta):
        fields = ["runtime_job", "runtime_session"]


class JobSerializer(serializers.JobSerializer):
    """
    Job serializer first version. Include basic fields from the initial model.
    """

    program = ProgramSerializer(many=False)

    class Meta(serializers.JobSerializer.Meta):
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


class JobSerializerWithoutResult(serializers.JobSerializer):
    """
    Job serializer first version. Include basic fields from the initial model.
    """

    program = ProgramSummarySerializer(many=False)

    class Meta(serializers.JobSerializer.Meta):
        fields = ["id", "status", "program", "created", "sub_status", "fleet_id", "compute_profile"]
