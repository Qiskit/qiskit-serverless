from django.http import HttpResponse
import json
import os
import requests
from django.conf import settings


def version(request):
    info = {"version": settings.RELEASE_VERSION}
    return HttpResponse(json.dumps(info))
