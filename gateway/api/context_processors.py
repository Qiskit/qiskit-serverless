"""Template context processors for the api app."""

from django.conf import settings


def w3id_sso(request):  # pylint: disable=unused-argument
    """Expose whether the optional w3id SSO login is available to templates.

    The "Login IBM SSO" button is only rendered when a client id is configured.
    """
    return {"w3id_sso_enabled": bool(getattr(settings, "W3ID_SSO_CLIENT_ID", ""))}
