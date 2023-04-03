"""
Serializers api for V1.
"""

from api import serializers


class NestedProgramSerializer(serializers.NestedProgramSerializer):
    """
    Nested program serializer first version. Include basic fields from the initial model.
    """

    class Meta(serializers.NestedProgramSerializer.Meta):
        fields = ["title", "entrypoint", "artifact", "dependencies", "arguments"]


class JobSerializer(serializers.JobSerializer):
    """
    Job serializer first version. Include basic fields from the initial model.
    """

    class Meta(serializers.JobSerializer.Meta):
        fields = ["id", "result", "status"]
