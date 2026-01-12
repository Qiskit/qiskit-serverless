"""Health check endpoints for Kubernetes readiness and liveness probes."""

from django.db import connection, OperationalError
from django.http import JsonResponse
from api.apps import ApiConfig


def readiness(request):
    """Probe meaning: service is ready to accept traffic.

    SSL redirect is enabled, but Kubernetes uses HTTP for its internal probes, so the endpoint
    was added to the SECURE_REDIRECT_EXEMPT property in settings.py.
    """

    if not ApiConfig.is_ready:
        return JsonResponse({"status": "api_config_not_ready"}, status=503)

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except OperationalError:
        return JsonResponse({"status": "database_unavailable"}, status=503)

    return JsonResponse({"status": "ready"})


def liveness(request):
    """Meaning: service is alive and running.

    SSL redirect is enabled, but Kubernetes uses HTTP for its internal probes, so the endpoint
    was added to the SECURE_REDIRECT_EXEMPT property in settings.py.

    """
    return JsonResponse({"status": "alive"})
