"""
Django Rest framework serializers for api application:
    - NestedProgramSerializer
    - JobSerializer

Version serializers inherit from the different serializers.
"""

from rest_framework import serializers

from .models import QuantumFunction, Job


class NestedProgramSerializer(serializers.ModelSerializer):
    """
    Serializer for the quantum function model.
    """

    class Meta:
        model = QuantumFunction


class JobSerializer(serializers.ModelSerializer):
    """
    Serializer for the job model.
    """

    class Meta:
        model = Job
