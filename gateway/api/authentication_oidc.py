"""OIDC authentication backend for the optional IBM w3id SSO backoffice login.

This backend is only wired into ``AUTHENTICATION_BACKENDS`` when
``SETTINGS_W3ID_SSO_ENABLED`` is true. It authenticates IBMers against w3id SSO
and maps them to a Django user whose username is the IBM id (e.g.
``IBMid-691000IC75``) and whose email goes into the email field, creating the
user on first login (``get_or_create`` semantics). Created users get no
permissions, so they reach an empty backoffice until an administrator grants
them access.
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


def extract_username(claims: dict) -> Optional[str]:
    """Return the Django username (the IBM id) from the w3id claims.

    The username is taken from the configured claim (default ``uid``) and an
    optional prefix is prepended to reproduce the full IBMid format
    (e.g. ``IBMid-`` + ``691000IC75``). Falls back to the email when the claim
    is absent, so a login never fails just because the IBM id is missing.
    """
    claim = getattr(settings, "SETTINGS_W3ID_SSO_USERNAME_CLAIM", "uid")
    prefix = getattr(settings, "SETTINGS_W3ID_SSO_USERNAME_PREFIX", "")
    value = claims.get(claim)
    if value:
        value = str(value).strip()
        if prefix and not value.startswith(prefix):
            value = f"{prefix}{value}"
        return value
    return extract_email(claims)


class W3IDSSOAuthenticationBackend(OIDCAuthenticationBackend):
    """Authenticate against w3id SSO and resolve a Django user by IBM id."""

    def verify_claims(self, claims):
        """Only accept logins that carry a usable email claim."""
        # Logged at debug so the exact claim names/values can be inspected when
        # wiring up a new environment (DEBUG must be on). Claims include PII.
        logger.debug("w3id SSO claims received: %s", claims)
        return extract_email(claims) is not None

    def filter_users_by_claims(self, claims):
        """Look up the existing Django user by IBM id (username), then email."""
        username = extract_username(claims)
        if username:
            by_username = self.UserModel.objects.filter(username__iexact=username)
            if by_username.exists():
                return by_username
        # Fall back to email so users created before this mapping still match.
        email = extract_email(claims)
        if email:
            return self.UserModel.objects.filter(email__iexact=email)
        return self.UserModel.objects.none()

    def create_user(self, claims):
        """Create a new backoffice user on first SSO login."""
        username = extract_username(claims)
        email = extract_email(claims) or ""
        is_staff = getattr(settings, "SETTINGS_W3ID_SSO_NEW_USER_IS_STAFF", True)
        user = self.UserModel.objects.create_user(username=username, email=email)
        if is_staff and not user.is_staff:
            user.is_staff = True
            user.save(update_fields=["is_staff"])
        logger.info(
            "New backoffice user created via w3id SSO: username=%s email=%s is_staff=%s",
            username,
            email,
            is_staff,
        )
        return user

    def update_user(self, user, claims):
        """Keep the stored email in sync with the w3id claims."""
        email = extract_email(claims)
        if email and user.email != email:
            user.email = email
            user.save(update_fields=["email"])
        return user
