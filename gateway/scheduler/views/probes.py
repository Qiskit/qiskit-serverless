"""Health check endpoints for Kubernetes readiness and liveness probes."""

from django.db import OperationalError, connection
from django.http import HttpRequest, JsonResponse
from api.apps import ApiConfig


def readiness(request: HttpRequest) -> JsonResponse:
    """Service is ready to accept traffic."""

    if not ApiConfig.is_ready:
        return JsonResponse({"status": "api_config_not_ready"}, status=503)

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except OperationalError:
        return JsonResponse({"status": "database_unavailable"}, status=503)

    return JsonResponse({"status": "ready"})


def liveness(request: HttpRequest) -> JsonResponse:
    """Service is alive and running."""
    return JsonResponse({"status": "alive"})
