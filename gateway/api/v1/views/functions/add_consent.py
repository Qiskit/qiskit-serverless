# pylint: disable=abstract-method
from typing import cast
from rest_framework.decorators import api_view, permission_classes
from rest_framework import serializers, permissions
from rest_framework.response import Response
from django.contrib.auth.models import AbstractUser
from api.v1.endpoint_handle_exceptions import endpoint_handle_exceptions
from api.v1.endpoint_decorator import endpoint
from api.use_cases.functions.add_consent import AddLogConsentUseCase


class InputSerializer(serializers.Serializer):
    """
    Validate and sanitize the input
    """

    accepted = serializers.BooleanField(required=True)
    provider = serializers.CharField(required=True)


@endpoint("programs/<str:title>/consent", name="add_consent")
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
    provider = validated_data["provider"]
    user = cast(AbstractUser, request.user)

    AddLogConsentUseCase().execute(user, title, provider, accepted)

    return Response({"message": "consent added"})
