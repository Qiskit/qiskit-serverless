"""
Django Rest framework serializers for api application:
    - NestedProgramSerializer
    - JobSerializer

Version serializers inherit from the different serializers.
"""

from rest_framework import serializers

from .models import NestedProgram, Job


class NestedProgramSerializer(serializers.ModelSerializer):
    """
    Serializer for the nested program model.
    """

    class Meta:
        model = NestedProgram


class JobSerializer(serializers.ModelSerializer):
    """
    Serializer for the job model.
    """

    class Meta:
        model = Job
