"""
Serializers api for V1.
"""

from rest_framework.serializers import ValidationError
from api import serializers


class ProgramSerializer(serializers.ProgramSerializer):
    """
    Program serializer first version. Include basic fields from the initial model.
    """

    class Meta(serializers.ProgramSerializer.Meta):
        fields = ["title", "entrypoint", "artifact", "dependencies", "provider"]


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
            "python_version",
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
