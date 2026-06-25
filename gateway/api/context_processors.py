"""Template context processors for the api app."""

from django.conf import settings


def w3id_sso(request):  # pylint: disable=unused-argument
    """Expose whether the optional w3id SSO login is enabled to templates.

    Used by the backoffice login template to conditionally render the
    "Login IBM SSO" button.
    """
    return {"w3id_sso_enabled": getattr(settings, "W3ID_SSO_ENABLED", False)}
