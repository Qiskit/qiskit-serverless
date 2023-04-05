"""
Serializers api for V1.
"""

from api import serializers


class QuantumFunctionSerializer(serializers.QuantumFunctionSerializer):
    """
    Quantum function serializer first version. Include basic fields from the initial model.
    """

    class Meta(serializers.QuantumFunctionSerializer.Meta):
        fields = ["title", "entrypoint", "artifact", "dependencies", "arguments"]


class JobSerializer(serializers.JobSerializer):
    """
    Job serializer first version. Include basic fields from the initial model.
    """

    class Meta(serializers.JobSerializer.Meta):
        fields = ["id", "result", "status"]
