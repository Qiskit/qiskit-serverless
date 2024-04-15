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


class RunAndRunExistingJobSerializer(serializers.RunAndRunExistingJobSerializer):
    """
    RunAndRunExistingJobSerializer is used by the /run and /run_existing end-points
    """

    class Meta(serializers.RunAndRunExistingJobSerializer.Meta):
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


class RunProgramSerializer(serializers.RunProgramSerializer):
    """
    RunProgram serializer is used in /run end-point
    """


class RunProgramModelSerializer(serializers.RunProgramModelSerializer):
    """
    RunProgram model serializer is used in /run end-point
    """

    class Meta(serializers.RunProgramModelSerializer.Meta):
        fields = [
            "title",
            "entrypoint",
            "artifact",
            "dependencies",
            "arguments",
            "config",
        ]
