"""
Jobs view api for V1.
"""

from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status
from rest_framework.decorators import action
from rest_framework.pagination import LimitOffsetPagination

from api import views
from api.permissions import IsOwner
from api.v1 import serializers as v1_serializers


class JobViewSet(views.JobViewSet):
    """
    Job view set first version. Use JobSerializer V1.
    """

    serializer_class = v1_serializers.JobSerializer
    pagination_class = LimitOffsetPagination
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_serializer_class(self):
        return v1_serializers.JobSerializer

    @staticmethod
    def get_serializer_job(*args, **kwargs):
        """
        Returns a `JobSerializer` instance
        """
        return v1_serializers.JobSerializer(*args, **kwargs)

    @staticmethod
    def get_serializer_job_without_result(*args, **kwargs):
        """
        Returns a `JobSerializerWithoutResult` instance
        """
        return v1_serializers.JobSerializerWithoutResult(*args, **kwargs)

    @swagger_auto_schema(
        operation_description="Get author Job",
        responses={status.HTTP_200_OK: v1_serializers.JobSerializer(many=False)},
    )
    def retrieve(self, request, pk=None):
        return super().retrieve(request, pk)

    @swagger_auto_schema(
        operation_description="Save the result of a job",
        responses={status.HTTP_200_OK: v1_serializers.JobSerializer(many=False)},
    )
    @action(methods=["POST"], detail=True)
    def result(self, request, pk=None):
        return super().result(request, pk)

    @swagger_auto_schema(
        operation_description="Update the sub status of a job",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=["sub_status"],
            properties={"sub_status": openapi.Schema(type=openapi.TYPE_STRING)},
            description="Value to populate the sub-status of a Job",
        ),
        responses={
            status.HTTP_200_OK: v1_serializers.JobSerializerWithoutResult(many=False),
            status.HTTP_400_BAD_REQUEST: openapi.Response(
                description="In case your request doesnt have a valid 'sub_status'.",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        "message": openapi.Schema(
                            type=openapi.TYPE_STRING,
                            example="'sub_status' not provided or is not valid",
                        )
                    },
                ),
            ),
            status.HTTP_403_FORBIDDEN: openapi.Response(
                description="In case you cannot change the sub_status.",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        "message": openapi.Schema(
                            type=openapi.TYPE_STRING,
                            example="Cannot update 'sub_status' when "
                            "is not  in RUNNING status. (Currently PENDING)",
                        )
                    },
                ),
            ),
            status.HTTP_404_NOT_FOUND: openapi.Response(
                description="In case the job doesnt exist or you dont have access to it.",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        "message": openapi.Schema(
                            type=openapi.TYPE_STRING, example="Job [XXXX] not found"
                        )
                    },
                ),
            ),
        },
    )
    @action(methods=["PATCH"], detail=True)
    def sub_status(self, request, pk=None):
        return super().sub_status(request, pk)

    @swagger_auto_schema(
        operation_description="Associate runtime job ids to a serverless job",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=["runtime_jobs"],
            properties={
                "runtime_jobs": openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Items(type=openapi.TYPE_STRING),
                    description="List of runtime job IDs to associate",
                )
            },
            description="Value to populate the sub-status of a Job",
        ),
        responses={
            status.HTTP_200_OK: v1_serializers.JobSerializerWithoutResult(many=False),
            status.HTTP_400_BAD_REQUEST: openapi.Response(
                description="In case your request doesnt have a valid 'runtime_jobs'.",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        "message": openapi.Schema(
                            type=openapi.TYPE_STRING,
                            example="'runtime_jobs' must be a list of strings",
                        )
                    },
                ),
            ),
            status.HTTP_404_NOT_FOUND: openapi.Response(
                description="In case the job doesnt exist or you dont have access to it.",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        "message": openapi.Schema(
                            type=openapi.TYPE_STRING, example="Job [XXXX] not found"
                        )
                    },
                ),
            ),
        },
    )
    @action(methods=["PATCH"], detail=True)
    def runtime_jobs(self, request, pk=None):
        return super().runtime_jobs(request, pk)

    @swagger_auto_schema(
        operation_description="Stop a job",
    )
    @action(methods=["POST"], detail=True)
    def stop(self, request, pk=None):
        return super().stop(request, pk)

    # We are not returning serializers in the rest of the end-points
