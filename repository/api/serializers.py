from rest_framework import serializers
from .models import NestedProgram


class NestedProgramSerializer(serializers.ModelSerializer):
    """
    TODO: documentation here
    """

    class Meta:
        model = NestedProgram
