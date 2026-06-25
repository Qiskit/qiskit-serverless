"""OIDC authentication backend for the optional IBM w3id SSO backoffice login.

The backend is always present in ``AUTHENTICATION_BACKENDS`` but only activates
on the SSO callback. It authenticates IBMers against w3id SSO
and maps them to a Django user keyed by their email address (used both as the
username and the email). On first login the user is created; it is never
granted or stripped of any flag (``is_staff``, ``is_superuser``, ``is_active``)
or permission, so a brand-new user has the Django defaults and an administrator
decides what access they get.

The email lookup is case-insensitive because usernames in the database may be
stored with different casing (e.g. ``Alberto@ibm.com``) than what w3id returns
(lowercase), and the stored email is normalized to lowercase on every login.
"""

import logging
from typing import Optional

from django.conf import settings
from django.shortcuts import redirect
from mozilla_django_oidc.auth import OIDCAuthenticationBackend
from mozilla_django_oidc.views import OIDCAuthenticationRequestView

logger = logging.getLogger("api.W3IDSSOAuthenticationBackend")

# Where to send the user when SSO is not usable (no client id) or after a failure.
NORMAL_LOGIN_URL = "/backoffice/login/"


def w3id_sso_login(request):
    """Entry point for the w3id SSO flow (one of our own urls).

    The SSO login is started from our own view, so we can decide here whether
    to contact the provider at all. When no client id is configured we never
    start a broken flow: the user is sent back to the standard backoffice login.
    Failures during the callback are handled by mozilla-django-oidc, which
    redirects to ``LOGIN_REDIRECT_URL_FAILURE`` (also the normal login).
    """
    if not settings.W3ID_SSO_CLIENT_ID:
        return redirect(NORMAL_LOGIN_URL)
    return OIDCAuthenticationRequestView.as_view()(request)


def extract_email(claims: dict) -> Optional[str]:
    """Return the user email from the w3id claims, normalized to lowercase.

    w3id maps the email to several attributes depending on the token
    (``sub`` in the ID token, ``emailAddress`` in userinfo), so we try the
    common keys and accept the first value that looks like an email.
    """
    for key in ("email", "emailAddress", "sub"):
        value = claims.get(key)
        if value and "@" in str(value):
            return str(value).strip().lower()
    return None


class W3IDSSOAuthenticationBackend(OIDCAuthenticationBackend):
    """Authenticate against w3id SSO and resolve a Django user by email."""

    def verify_claims(self, claims):
        """Only accept logins that carry a usable email claim."""
        return extract_email(claims) is not None

    def filter_users_by_claims(self, claims):
        """Look up the existing Django user by email, ignoring case.

        The username may have been stored with different casing than what w3id
        returns, so the match is case-insensitive to avoid creating duplicates.
        """
        email = extract_email(claims)
        if not email:
            return self.UserModel.objects.none()
        return self.UserModel.objects.filter(username__iexact=email)

    def create_user(self, claims):
        """Create a new backoffice user on first SSO login.

        Only the username and email are set; no flag or permission is touched,
        so the user is created with Django defaults (no staff, no superuser).
        """
        email = extract_email(claims)
        user = self.UserModel.objects.create_user(username=email, email=email)
        logger.info("New backoffice user created via w3id SSO: %s", email)
        return user

    def update_user(self, user, claims):
        """Normalize the stored email to lowercase on every login.

        No flag is modified, only the email field is kept in sync.
        """
        email = extract_email(claims)
        if email and user.email != email:
            user.email = email
            user.save(update_fields=["email"])
        return user
