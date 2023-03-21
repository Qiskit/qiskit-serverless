"""Serializers."""

from rest_framework import serializers

from api.models import NestedProgram, Job


class ProgramSerializer(serializers.ModelSerializer):
    """ProgramSerializer."""

    class Meta:
        model = NestedProgram
        fields = ["title", "entrypoint", "artifact", "dependencies", "arguments"]


class JobSerializer(serializers.ModelSerializer):
    """JobSerializer."""

    class Meta:
        model = Job
        fields = ["id", "result", "status"]
