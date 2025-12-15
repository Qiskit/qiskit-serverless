"""Health check endpoints for Kubernetes readiness and liveness probes."""

from django.db import connection, OperationalError
from django.http import JsonResponse
from api.apps import ApiConfig


def readiness(request):
    """Readiness probe endpoint - indicates the service is ready to accept traffic."""
    return JsonResponse({"status": "ready"})


def liveness(request):
    """Liveness probe endpoint - indicates the service is alive and running."""
    return JsonResponse({"status": "alive"})
