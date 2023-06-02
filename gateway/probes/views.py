from django.http import HttpResponse
import os
import requests


def readiness(request):
    try:
        resp = requests.get(os.environ.get("RAY_HOST", "http://ray") + "/api/jobs/")
    except Exception as err:
        print(err)
        return HttpResponse(status=503)
    if 200 <= resp.status_code and resp.status_code < 500:
        return HttpResponse("Hi! I'm ready.")
    else:
        return HttpResponse(status=503)


def liveness(request):
    return HttpResponse("Hi! I'm alive.")
