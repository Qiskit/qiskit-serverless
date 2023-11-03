"""
Serializers api for V1.
"""

from api import serializers


class JobConfigSerializer(serializers.JobConfigSerializer):
    """
    Job Config serializer first version. Include basic fields from the initial model.
    """

    class Meta(serializers.JobConfigSerializer.Meta):
        fields = [
            "workers",
            "min_workers",
            "max_workers",
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
