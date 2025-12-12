"""Health check endpoints for Kubernetes readiness and liveness probes."""

from django.http import JsonResponse


def readiness(request):
    """Readiness probe endpoint - indicates the service is ready to accept traffic."""
    return JsonResponse({"status": "ready"})


def liveness(request):
    """Liveness probe endpoint - indicates the service is alive and running."""
    return JsonResponse({"status": "alive"})
