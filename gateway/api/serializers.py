"""
Django Rest framework serializers for api application:
    - QuantumFunctionSerializer
    - JobSerializer

Version serializers inherit from the different serializers.
"""

from rest_framework import serializers

from .models import Program, Job


class QuantumFunctionSerializer(serializers.ModelSerializer):
    """
    Serializer for the quantum function model.
    """

    class Meta:
        model = Program


class JobSerializer(serializers.ModelSerializer):
    """
    Serializer for the job model.
    """

    class Meta:
        model = Job
