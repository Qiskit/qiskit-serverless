from django.http import HttpResponse
import os
import requests


def readiness(request):
    return HttpResponse("Hi! I'm ready.")


def liveness(request):
    return HttpResponse("Hi! I'm alive.")
