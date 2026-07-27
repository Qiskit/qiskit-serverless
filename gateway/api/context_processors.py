"""Template context processors for the api app."""

from api.authentication_oidc import w3id_sso_enabled


def w3id_sso(request):  # pylint: disable=unused-argument
    """Expose whether the optional w3id SSO login is available to templates.

    The "Login IBM SSO" button is only rendered when SSO is fully configured
    (both client id and secret present).
    """
    return {"w3id_sso_enabled": w3id_sso_enabled()}
