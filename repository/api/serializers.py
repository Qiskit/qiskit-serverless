from rest_framework import serializers
from .models import NestedProgram
from .validators.list_validator import ListValidator


class NestedProgramSerializer(serializers.ModelSerializer):
    """
    TODO: documentation here
    """

    class Meta:
        model = NestedProgram
        validators = [ListValidator(fields=["dependencies", "tags"], nullable=True)]
