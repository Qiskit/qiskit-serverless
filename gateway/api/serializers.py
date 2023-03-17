"""Serializers."""

from rest_framework import serializers

from api.models import Program, Job


class ProgramSerializer(serializers.ModelSerializer):
    """ProgramSerializer."""

    class Meta:
        model = Program
        fields = ["title", "entrypoint", "artifact", "dependencies", "arguments"]


class JobSerializer(serializers.ModelSerializer):
    """JobSerializer."""

    class Meta:
        model = Job
        fields = ["id", "result", "status"]
