"""
Serializers api for V1.
"""

import json
import logging
from packaging.requirements import Requirement
from rest_framework.serializers import ValidationError
from api import serializers
from api.models import Provider
from api.utils import (
    create_dependency_allowlist,
    create_dependency_grammar,
    create_dynamic_deps_whitelist,
    parse_dependency,
)

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


class UploadProgramSerializer(serializers.UploadProgramSerializer):
    """
    UploadProgramSerializer is used by the /upload end-point
    """

    def validate_image(self, value):
        """Validaes image."""
        # place to add image validation
        return value

    def validate(self, attrs):  # pylint: disable=too-many-branches
        """Validates serializer data."""
        entrypoint = attrs.get("entrypoint", None)
        image = attrs.get("image", None)
        if entrypoint is None and image is None:
            raise ValidationError(
                "At least one of attributes (entrypoint, image) is required."
            )

        # validate dependencies
        # dependency_grammar = create_dependency_grammar()
        # deps = json.loads(attrs.get("dependencies", None))
        # allowlist = create_dependency_allowlist()
        # if len(allowlist.keys()) > 0:  # If no allowlist, all dependencies allowed
        #     for d in deps:
        #         dep, _ = parse_dependency(d, dependency_grammar)
        #         # Determine if a dependency is allowed
        #         if dep not in allowlist:
        #             raise ValidationError(f"Dependency {dep} is not allowed")

        # validate dependencies
        deps = attrs.get("dependencies", None)
        deps = filter(lambda dep: not dep.startswith("#") and dep, deps.splitlines())
        if len(list(deps)):
            whitelist_deps = create_dynamic_deps_whitelist()
            required_deps = [
                Requirement(dep)
                for dep in deps
            ]
            # can we improve this?
            if any(len(req.specifier) > 1 or list(req.specifier)[0].operator == "==" for req in required_deps):
                raise ValidationError("Dependencies needs a fixed version using the '==' operator.")
            
            for req in required_deps:
              any(
                  req.name == white.name 
                  and list(req.specifier)[0].version in white.specifier 
                  for white in whitelist_deps
              )


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


class JobSerializer(serializers.JobSerializer):
    """
    Job serializer first version. Include basic fields from the initial model.
    """

    program = ProgramSerializer(many=False)

    class Meta(serializers.JobSerializer.Meta):
        fields = ["id", "result", "status", "program", "created", "sub_status"]


class JobSerializerWithoutResult(serializers.JobSerializer):
    """
    Job serializer first version. Include basic fields from the initial model.
    """

    program = ProgramSerializer(many=False)

    class Meta(serializers.JobSerializer.Meta):
        fields = ["id", "status", "program", "created", "sub_status"]


class RuntimeJobSerializer(serializers.RuntimeJobSerializer):
    """
    Runtime job serializer first version. Serializer for the runtime job model.
    """

    job = JobSerializer(many=False)

    class Meta(serializers.RuntimeJobSerializer.Meta):
        fields = ["job", "runtime_job"]


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
