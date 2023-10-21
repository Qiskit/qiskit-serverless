"""
Serializers api for V1.
"""

from api import serializers


class ProgramConfigSerializer(serializers.ProgramSerializer):
    """
    Program Config serializer first version. Include basic fields from the initial model.
    """

    class Meta(serializers.ProgramConfigSerializer.Meta):
        fields = [
            "workers",
            "min_workers",
            "max_workers",
            "worker_cpu",
            "worker_mem",
            "auto_scaling",
        ]


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
        ]


class JobSerializer(serializers.JobSerializer):
    """
    Job serializer first version. Include basic fields from the initial model.
    """

    program = ProgramSerializer(many=False)

    class Meta(serializers.JobSerializer.Meta):
        fields = ["id", "result", "status", "program", "created"]
