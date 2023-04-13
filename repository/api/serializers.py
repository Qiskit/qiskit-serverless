"""
Django Rest framework serializers for api application:
    - QuantumFunctionSerializer

Version serializers inherit from the different serializers.
"""

from rest_framework import serializers
from .models import Program
from .validators import list_validator, dict_validator


class QuantumFunctionSerializer(serializers.ModelSerializer):
    """
    Serializer for the quantum function model.
    """

    class Meta:
        model = Program
        validators = [
            list_validator.ListValidator(
                fields=["dependencies", "tags"], nullable=True
            ),
            dict_validator.DictValidator(
                fields=["env_vars", "arguments"], nullable=True
            ),
        ]
