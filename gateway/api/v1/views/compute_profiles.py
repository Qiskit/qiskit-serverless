"""
API V1: Compute profiles end-point.
"""

import logging
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.decorators import permission_classes

from api.use_cases.compute_profiles import ComputeProfilesUseCase
from api.v1.endpoint_decorator import endpoint
from api.v1.views.serializer_utils import ComputeProfileSerializer

logger = logging.getLogger("api.api.v1.views.compute_profiles")


@swagger_auto_schema(
    method="get",
    operation_description=(
        "Get the compute profiles registered on this deployment, i.e. the catalog an uploader "
        "can name (by compute_profile_id) in a function's sizes_map."
    ),
    responses={
        status.HTTP_200_OK: ComputeProfileSerializer(many=True),
        status.HTTP_401_UNAUTHORIZED: "Authentication credentials were not provided or are invalid.",
    },
)
@endpoint("compute-profiles", method="GET")
@permission_classes([permissions.IsAuthenticated])
def compute_profiles(request):
    """
    Registered compute profiles end-point
    """
    profiles = ComputeProfilesUseCase().execute()
    serializer = ComputeProfileSerializer(profiles, many=True)
    logger.info("[compute-profiles] user_id=%s | Compute profiles ok", request.user.id)
    return Response(serializer.data)
