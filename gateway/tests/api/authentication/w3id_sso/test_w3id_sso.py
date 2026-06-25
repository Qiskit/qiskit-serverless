"""Tests for the optional IBM w3id SSO (OIDC) backoffice authentication backend."""

import pytest

from api.authentication_oidc import (
    W3IDSSOAuthenticationBackend,
    extract_email,
    extract_username,
)

# Access the db so users can be created/rolled back per test.
pytestmark = pytest.mark.django_db


@pytest.fixture(name="oidc_settings")
def _oidc_settings(settings):
    """Minimal OIDC settings so the backend can be instantiated in tests."""
    settings.OIDC_RP_CLIENT_ID = "test-client-id"
    settings.OIDC_RP_CLIENT_SECRET = "test-client-secret"
    settings.OIDC_OP_AUTHORIZATION_ENDPOINT = "https://test.login.w3.ibm.com/authorize"
    settings.OIDC_OP_TOKEN_ENDPOINT = "https://test.login.w3.ibm.com/token"
    settings.OIDC_OP_USER_ENDPOINT = "https://test.login.w3.ibm.com/userinfo"
    settings.OIDC_OP_JWKS_ENDPOINT = "https://test.login.w3.ibm.com/jwks"
    settings.SETTINGS_W3ID_SSO_NEW_USER_IS_STAFF = True
    settings.SETTINGS_W3ID_SSO_USERNAME_CLAIM = "uid"
    settings.SETTINGS_W3ID_SSO_USERNAME_PREFIX = ""
    return settings


def test_extract_email_from_common_claims():
    """The email is taken from any of the keys w3id may use, lowercased."""
    assert extract_email({"email": "Alice@IBM.com"}) == "alice@ibm.com"
    assert extract_email({"emailAddress": "bob@ibm.com"}) == "bob@ibm.com"
    assert extract_email({"sub": "carol@ibm.com"}) == "carol@ibm.com"
    assert extract_email({"sub": "not-an-email", "email": "dan@ibm.com"}) == "dan@ibm.com"


def test_extract_email_returns_none_when_absent():
    """No usable email claim results in None (login is rejected)."""
    assert extract_email({"sub": "12345"}) is None
    assert extract_email({}) is None


def test_extract_username_from_claim(oidc_settings):
    """The username comes from the configured claim verbatim."""
    assert extract_username({"uid": "691000IC75", "email": "a@ibm.com"}) == "691000IC75"


def test_extract_username_with_prefix(oidc_settings):
    """A prefix reproduces the full IBMid format without doubling it."""
    oidc_settings.SETTINGS_W3ID_SSO_USERNAME_PREFIX = "IBMid-"
    assert extract_username({"uid": "691000IC75"}) == "IBMid-691000IC75"
    # Already-prefixed values are left untouched.
    assert extract_username({"uid": "IBMid-691000IC75"}) == "IBMid-691000IC75"


def test_extract_username_custom_claim(oidc_settings):
    """The claim that holds the IBM id is configurable."""
    oidc_settings.SETTINGS_W3ID_SSO_USERNAME_CLAIM = "preferred_username"
    assert extract_username({"preferred_username": "IBMid-691000IC75"}) == "IBMid-691000IC75"


def test_extract_username_falls_back_to_email(oidc_settings):
    """When the IBM id claim is missing, the email is used as username."""
    assert extract_username({"email": "fallback@ibm.com"}) == "fallback@ibm.com"


def test_create_user_keyed_by_ibm_id_with_email(oidc_settings):
    """A new user gets the IBM id as username and the email in the email field."""
    oidc_settings.SETTINGS_W3ID_SSO_USERNAME_PREFIX = "IBMid-"
    backend = W3IDSSOAuthenticationBackend()

    user = backend.create_user({"uid": "691000IC75", "email": "Newuser@ibm.com"})

    assert user.username == "IBMid-691000IC75"
    assert user.email == "newuser@ibm.com"
    assert user.is_staff is True
    assert user.is_superuser is False
    assert list(user.groups.all()) == []
    assert user.get_all_permissions() == set()


def test_create_user_without_staff_when_disabled(oidc_settings):
    """When the staff flag is off, created users cannot reach the backoffice."""
    oidc_settings.SETTINGS_W3ID_SSO_NEW_USER_IS_STAFF = False
    backend = W3IDSSOAuthenticationBackend()

    user = backend.create_user({"uid": "691000IC75", "emailAddress": "noaccess@ibm.com"})

    assert user.username == "691000IC75"
    assert user.is_staff is False


def test_filter_users_by_claims_finds_existing_by_ibm_id(oidc_settings):
    """An existing user is matched by IBM id so login is idempotent (get_or_create)."""
    backend = W3IDSSOAuthenticationBackend()
    created = backend.create_user({"uid": "691000IC75", "email": "existing@ibm.com"})

    found = backend.filter_users_by_claims({"uid": "691000IC75", "email": "existing@ibm.com"})

    assert list(found) == [created]


def test_filter_users_by_claims_falls_back_to_email(oidc_settings):
    """Users created before the IBM id mapping are still matched by email."""
    backend = W3IDSSOAuthenticationBackend()
    created = backend.UserModel.objects.create_user(username="legacy@ibm.com", email="legacy@ibm.com")

    # Same person logging in now, with an IBM id that has no user yet.
    found = backend.filter_users_by_claims({"uid": "999999XX99", "email": "legacy@ibm.com"})

    assert list(found) == [created]


def test_verify_claims(oidc_settings):
    """Only claims carrying an email are accepted."""
    backend = W3IDSSOAuthenticationBackend()
    assert backend.verify_claims({"email": "ok@ibm.com"}) is True
    assert backend.verify_claims({"uid": "691000IC75"}) is False
