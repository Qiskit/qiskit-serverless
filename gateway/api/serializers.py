from rest_framework import serializers

from api.models import Program, Job


class ProgramSerializer(serializers.ModelSerializer):
    class Meta:
        model = Program
        fields = ["title", "entrypoint", "artifact"]


class JobSerializer(serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = ["id", "result", "status"]
