"""
Serializers api for V1.
"""

from api import serializers


class ProgramSerializer(serializers.ProgramSerializer):
    """
    Program serializer first version. Include basic fields from the initial model.
    """

    class Meta(serializers.ProgramSerializer.Meta):
        fields = [
            "title",
            "entrypoint",
            "artifact",
            "dependencies",
            "arguments",
            "public",
        ]


class UploadProgramSerializer(serializers.UploadProgramSerializer):
    """
    UploadProgramSerializer is used by the /upload end-point
    """

    class Meta(serializers.UploadProgramSerializer.Meta):
        fields = [
            "title",
            "entrypoint",
            "artifact",
            "dependencies",
            "arguments",
        ]


class RunExistingProgramSerializer(serializers.RunExistingProgramSerializer):
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


class CatalogEntrySerializer(serializers.CatalogEntrySerializer):
    """
    Catalog entry serializer first version. Serializer for the catalog entry model.
    """

    program = ProgramSerializer(many=False)

    class Meta(serializers.CatalogEntrySerializer.Meta):
        fields = [
            "id",
            "title",
            "description",
            "tags",
            "created",
            "updated",
            "program",
            "status",
        ]


class ToCatalogSerializer(serializers.ToCatalogSerializer):
    """
    To catalog serializer first version.
    This serializer limitates the fields from CatalogEntry.
    """
