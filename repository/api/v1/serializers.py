"""
Serializers api for V1.
"""

from api import serializers


class QuantumFunctionSerializer(serializers.QuantumFunctionSerializer):
    """
    Nested program serializer first version. Include basic fields from the initial model.
    """

    class Meta(serializers.QuantumFunctionSerializer.Meta):
        fields = (
            "id",
            "created",
            "updated",
            "title",
            "description",
            "entrypoint",
            "working_dir",
            "version",
            "dependencies",
            "env_vars",
            "arguments",
            "tags",
            "public",
            "artifact",
        )
