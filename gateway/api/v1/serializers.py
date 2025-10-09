"""
Serializers api for V1.
"""

import json
import logging
from typing import Any
from packaging.requirements import Requirement, InvalidRequirement
from rest_framework.serializers import ValidationError
from api import serializers
from api.models import Provider
from api.utils import check_whitelisted

logger = logging.getLogger("gateway.serializers")


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

    def validate_image(self, value):
        """Validates image."""
        # place to add image validation
        return value

    def _parse_dependency(self, dep: Any):
        if not isinstance(dep, dict) and not isinstance(dep, str):
            raise ValidationError(
                "'dependencies' should be an array with strings or dict."
            )

        if isinstance(dep, str):
            dep_string = dep
        else:
            dep_name = list(dep.keys())
            if len(dep_name) > 1 or len(dep_name) == 0:
                raise ValidationError(
                    "'dependencies' should be an array with dict containing one dependency only."
                )
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

        if len(req_specifier_list) > 1 or (
            req_specifier_first and req_specifier_first.operator != "=="
        ):
            raise ValidationError(
                "'dependencies' needs one fixed version using the '==' operator."
            )

        return requirement

    def _validate_deps(self, deps):
        if not isinstance(deps, list):
            raise ValidationError("'dependencies' should be an array.")

        if len(deps) == 0:
            return

        try:
            required_deps = [self._parse_dependency(dep) for dep in deps]
        except InvalidRequirement as invalid_requirement:
            raise ValidationError(
                "Error while parsing dependencies."
            ) from invalid_requirement

        try:
            check_whitelisted(required_deps)
        except ValueError as value_error:
            raise ValidationError(value_error.args[0]) from value_error

    def validate(self, attrs):  # pylint: disable=too-many-branches
        """Validates serializer data."""
        entrypoint = attrs.get("entrypoint", None)
        image = attrs.get("image", None)
        if entrypoint is None and image is None:
            raise ValidationError(
                "At least one of attributes (entrypoint, image) is required."
            )
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
            raise ValidationError(
                "Qiskit Function title is malformed. It can only contain one slash."
            )

        if image is not None:
            if provider is None and len(title_split) != 2:
                raise ValidationError(
                    "Custom images are only available if you are a provider."
                )
            if not provider:
                provider = title_split[0]
            provider_instance = Provider.objects.filter(name=provider).first()
            if provider_instance is None:
                raise ValidationError(f"{provider} is not valid provider.")
            if provider_instance.registry and not image.startswith(
                provider_instance.registry
            ):
                raise ValidationError(
                    f"Custom images must be in {provider_instance.registry}."
                )

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
        fields = ["id", "result", "status", "program", "created", "arguments"]


class RuntimeJobSerializer(serializers.RuntimeJobSerializer):
    """
    Runtime job serializer first version. Serializer for the runtime job model.
    """

    job = serializers.JobSerializer(many=False)

    class Meta(serializers.RuntimeJobSerializer.Meta):
        fields = ["job", "runtime_job", "runtime_session"]


class JobSerializer(serializers.JobSerializer):
    """
    Job serializer first version. Include basic fields from the initial model.
    """

    runtime_jobs = RuntimeJobSerializer(many=True, read_only=True)

    class Meta(serializers.JobSerializer.Meta):
        fields = [
            "id",
            "result",
            "status",
            "program",
            "created",
            "sub_status",
            "runtime_jobs",
        ]


class JobSerializerWithoutResult(serializers.JobSerializer):
    """
    Job serializer first version. Include basic fields from the initial model.
    """

    program = ProgramSummarySerializer(many=False)

    class Meta(serializers.JobSerializer.Meta):
        fields = ["id", "status", "program", "created", "sub_status"]


class CatalogProviderSerializer(serializers.CatalogProviderSerializer):
    """
    Serializer for the Provider model in the Catalog View.
    """

    class Meta(serializers.CatalogProviderSerializer.Meta):
        fields = ["name", "readable_name", "url", "icon_url"]


class ListCatalogSerializer(serializers.ListCatalogSerializer):
    """
    List Serializer for the Catalog View.
    """

    provider = CatalogProviderSerializer()

    class Meta(serializers.ListCatalogSerializer.Meta):
        fields = [
            "id",
            "title",
            "readable_title",
            "type",
            "description",
            "provider",
            "available",
        ]


class RetrieveCatalogSerializer(serializers.RetrieveCatalogSerializer):
    """
    Retrieve Serializer for the Catalog View.
    """

    provider = CatalogProviderSerializer()

    class Meta(serializers.RetrieveCatalogSerializer.Meta):
        fields = [
            "id",
            "title",
            "readable_title",
            "type",
            "description",
            "documentation_url",
            "provider",
            "available",
            "additional_info",
        ]
