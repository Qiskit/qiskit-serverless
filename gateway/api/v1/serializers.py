"""
Serializers api for V1.
"""

import json
from rest_framework.serializers import ValidationError
from api import serializers
from api.models import Provider


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
        ]


class UploadProgramSerializer(serializers.UploadProgramSerializer):
    """
    UploadProgramSerializer is used by the /upload end-point
    """

    def validate_image(self, value):
        """Validaes image."""
        # place to add image validation
        return value

    def validate(self, attrs):
        """Validates serializer data."""
        entrypoint = attrs.get("entrypoint", None)
        image = attrs.get("image", None)
        if entrypoint is None and image is None:
            raise ValidationError(
                "At least one of attributes (entrypoint, image) is required."
            )

        # validate dependencies
        # allowlist stored in json config file (eventually via configmap)
        # sample:
        # allowlist = { "wheel": ["0.44.0", "0.43.2"] }
        # where the values for each key are allowed versions of dependency
        deps = json.loads(attrs.get("dependencies", None))
        with open("api/v1/allowlist.json") as f:
            allowlist = json.load(f)

        # If no allowlist specified, all dependencies allowed
        if len(allowlist.keys()) > 0:
            for d in deps:
                dep, ver = d.split("==")

                # Determine if a dependency is allowed
                if not allowlist[dep]:
                    raise ValidationError(f"Dependency {dep} is not allowed")

                # Determine if a specific version of a dependency is allowed
                if ver not in allowlist[dep]:
                    raise ValidationError(f"Version {ver} of dependency {dep} is not allowed")


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
        ]


class RunProgramSerializer(serializers.RunProgramSerializer):
    """
    RunExistingProgramSerializer is used by the /upload end-point
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
        fields = ["id", "result", "status", "program", "created"]


class RuntimeJobSerializer(serializers.RuntimeJobSerializer):
    """
    Runtime job serializer first version. Serializer for the runtime job model.
    """

    job = JobSerializer(many=False)

    class Meta(serializers.RuntimeJobSerializer.Meta):
        fields = ["job", "runtime_job"]
