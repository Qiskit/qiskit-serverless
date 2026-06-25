"""Tests for the optional IBM w3id SSO (OIDC) backoffice authentication backend."""

import pytest

from api.authentication_oidc import W3IDSSOAuthenticationBackend, extract_email

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
    return settings


def test_extract_email_lowercases_common_claims():
    """The email is taken from any of the keys w3id may use, lowercased."""
    assert extract_email({"email": "Alice@IBM.com"}) == "alice@ibm.com"
    assert extract_email({"emailAddress": "Bob@ibm.com"}) == "bob@ibm.com"
    assert extract_email({"sub": "Carol@ibm.com"}) == "carol@ibm.com"
    assert extract_email({"sub": "not-an-email", "email": "dan@ibm.com"}) == "dan@ibm.com"


def test_extract_email_returns_none_when_absent():
    """No usable email claim results in None (login is rejected)."""
    assert extract_email({"sub": "12345"}) is None
    assert extract_email({}) is None


def test_create_user_keyed_by_email_with_staff(oidc_settings):
    """A new user is created with the (lowercased) email as username and staff access."""
    backend = W3IDSSOAuthenticationBackend()

    user = backend.create_user({"email": "NewUser@ibm.com"})

    assert user.username == "newuser@ibm.com"
    assert user.email == "newuser@ibm.com"
    assert user.is_staff is True
    assert user.is_superuser is False
    assert list(user.groups.all()) == []
    assert user.get_all_permissions() == set()


def test_create_user_without_staff_when_disabled(oidc_settings):
    """When the staff flag is off, created users cannot reach the backoffice."""
    oidc_settings.SETTINGS_W3ID_SSO_NEW_USER_IS_STAFF = False
    backend = W3IDSSOAuthenticationBackend()

    user = backend.create_user({"emailAddress": "noaccess@ibm.com"})

    assert user.username == "noaccess@ibm.com"
    assert user.is_staff is False


def test_filter_users_by_claims_is_case_insensitive(oidc_settings):
    """An existing user stored with different casing is still matched (no duplicate)."""
    backend = W3IDSSOAuthenticationBackend()
    existing = backend.UserModel.objects.create_user(username="Alberto@ibm.com", email="Alberto@ibm.com")

    found = backend.filter_users_by_claims({"email": "alberto@ibm.com"})

    assert list(found) == [existing]


def test_filter_users_by_claims_empty_without_email(oidc_settings):
    """No email claim yields no candidate users."""
    backend = W3IDSSOAuthenticationBackend()
    assert list(backend.filter_users_by_claims({"sub": "12345"})) == []


def test_update_user_lowercases_stored_email(oidc_settings):
    """On login, a mixed-case stored email is normalized to lowercase."""
    backend = W3IDSSOAuthenticationBackend()
    user = backend.UserModel.objects.create_user(username="Alberto@ibm.com", email="Alberto@ibm.com")

    updated = backend.update_user(user, {"email": "alberto@ibm.com"})
    updated.refresh_from_db()

    assert updated.email == "alberto@ibm.com"
    # The username is intentionally left untouched to avoid renaming accounts.
    assert updated.username == "Alberto@ibm.com"


def test_verify_claims(oidc_settings):
    """Only claims carrying an email are accepted."""
    backend = W3IDSSOAuthenticationBackend()
    assert backend.verify_claims({"email": "ok@ibm.com"}) is True
    assert backend.verify_claims({"sub": "12345"}) is False
