from django.http import HttpResponse
import json
import os
import requests
import main.settings


def version(request):
    info = {"version": main.settings.RELEASE_VERSION}
    return HttpResponse(json.dumps(info))
