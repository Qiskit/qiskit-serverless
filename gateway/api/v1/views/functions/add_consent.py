from typing import cast
from rest_framework.decorators import api_view, permission_classes
from rest_framework import serializers, permissions
from django.contrib.auth.models import AbstractUser
from api.v1.endpoint_handle_exceptions import endpoint_handle_exceptions
from api.v1.endpoint_decorator import endpoint
from api.use_cases.functions.add_consent import AddLogConsentUseCase


class InputSerializer(serializers.Serializer):
    """
    Validate and sanitize the input
    """

    accepted = serializers.CharField(required=True)

    def create(self, validated_data):
        """Not implemented - this serializer is for validation only."""
        raise NotImplementedError

    def update(self, instance, validated_data):
        """Not implemented - this serializer is for validation only."""
        raise NotImplementedError


@endpoint("programs/<str:title>", name="add_consent")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def add_consent(request, title):
    """
    Handle user consent for a program.

    This endpoint allows authenticated users to provide their consent for a specific program.

    Args:
        request: The HTTP request object containing the consent data
        title (str): The title of the program for which consent is being given

    Returns:
        Response: Django REST framework response object
    """
    serializer = InputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    validated_data = serializer.validated_data

    accepted = validated_data["accepted"]
    user = cast(AbstractUser, request.user)

    AddLogConsentUseCase().execute(user, title, accepted)
