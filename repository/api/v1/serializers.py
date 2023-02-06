from api import serializers


class NestedProgramSerializer(serializers.NestedProgramSerializer):
    """
    TODO: documentation here
    """

    class Meta(serializers.NestedProgramSerializer.Meta):
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
        )
