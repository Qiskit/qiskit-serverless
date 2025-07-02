from django.http import JsonResponse


def readiness(request):
    return JsonResponse({"status": "ready"})


def liveness(request):
    return JsonResponse({"status": "alive"})
