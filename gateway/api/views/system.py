"""System-level endpoints for application information (version), status, etc."""

from django.http import JsonResponse

import main.settings


def version(request):
    """Return the current application version."""
    info = {"version": main.settings.RELEASE_VERSION}
    return JsonResponse(info)
