from rest_framework import serializers
from .models import NestedProgram


class NestedProgramSerializer(serializers.ModelSerializer):
    class Meta:
        model = NestedProgram
        fields = '__all__'
