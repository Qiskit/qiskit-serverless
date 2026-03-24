"""Health check endpoints for Kubernetes liveness probe."""

from django.http import HttpRequest, JsonResponse, HttpResponse

from scheduler.health import SchedulerHealth


def make_liveness(health: SchedulerHealth):
    """Return a liveness handler bound to the given health state."""

    def liveness(request: HttpRequest) -> JsonResponse:
        """Returns 503 if consecutive DB errors have exceeded the unhealthy threshold."""
        if health.is_unhealthy:
            return JsonResponse({"status": "db_error_threshold_exceeded"}, status=503)
        return JsonResponse({"status": "alive"})

    return liveness


def not_found(request: HttpRequest) -> HttpResponse:
    """Route not found."""
    return HttpResponse("Not found", status=404)
