"""OIDC authentication backend for the optional IBM w3id SSO backoffice login.

This backend is only wired into ``AUTHENTICATION_BACKENDS`` when
``SETTINGS_W3ID_SSO_ENABLED`` is true. It authenticates IBMers against w3id SSO
and maps them to a Django user keyed by their email address, creating the user
on first login (``get_or_create`` semantics). Created users get no permissions,
so they reach an empty backoffice until an administrator grants them access.
"""

import logging
from typing import Optional

from django.conf import settings
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

logger = logging.getLogger("api.W3IDSSOAuthenticationBackend")


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
        """Look up the existing Django user by email (used as the username)."""
        email = extract_email(claims)
        if not email:
            return self.UserModel.objects.none()
        return self.UserModel.objects.filter(username__iexact=email)

    def create_user(self, claims):
        """Create a new backoffice user on first SSO login."""
        email = extract_email(claims)
        is_staff = getattr(settings, "SETTINGS_W3ID_SSO_NEW_USER_IS_STAFF", True)
        user = self.UserModel.objects.create_user(username=email, email=email)
        if is_staff and not user.is_staff:
            user.is_staff = True
            user.save(update_fields=["is_staff"])
        logger.info("New backoffice user created via w3id SSO: %s (is_staff=%s)", email, is_staff)
        return user

    def update_user(self, user, claims):
        """Keep the stored email in sync with the w3id claims."""
        email = extract_email(claims)
        if email and user.email != email:
            user.email = email
            user.save(update_fields=["email"])
        return user
