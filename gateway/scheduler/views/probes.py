"""Health check endpoints for Kubernetes readiness and liveness probes."""

from django.db import OperationalError, connection
from django.http import HttpRequest, JsonResponse, HttpResponse


def readiness(request: HttpRequest) -> JsonResponse:
    """Service is ready to accept traffic."""

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except OperationalError:
        return JsonResponse({"status": "database_unavailable"}, status=503)

    return JsonResponse({"status": "ready"})


def liveness(request: HttpRequest) -> JsonResponse:
    """Service is alive and running."""
    return JsonResponse({"status": "alive"})


def not_found(request: HttpRequest) -> HttpResponse:
    """Route not found."""
    return HttpResponse("Not found", status=404)
