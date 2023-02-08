from rest_framework import serializers
from .models import NestedProgram
from .validators import list_validator, dict_validator


class NestedProgramSerializer(serializers.ModelSerializer):
    """
    TODO: documentation here
    """

    class Meta:
        model = NestedProgram
        validators = [
            list_validator.ListValidator(
                fields=["dependencies", "tags"], nullable=True
            ),
            dict_validator.DictValidator(
                fields=["env_vars", "arguments"], nullable=True
            ),
        ]
