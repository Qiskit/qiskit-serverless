"""
Serializers api for V1.
"""

from api import serializers


class ProgramSerializer(serializers.ProgramSerializer):
    """
    Program serializer first version. Include basic fields from the initial model.
    """

    class Meta(serializers.ProgramSerializer.Meta):
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
