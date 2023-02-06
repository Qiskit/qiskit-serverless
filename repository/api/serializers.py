from rest_framework import serializers
from .models import NestedProgram
from .validators import list


class NestedProgramSerializer(serializers.ModelSerializer):
    """
    TODO: documentation here
    """

    class Meta:
        model = NestedProgram
        validators = [list.List(fields=["dependencies", "tags"], nullable=True)]
