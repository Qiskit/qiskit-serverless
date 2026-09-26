# This code is part of a Qiskit project.
#
# (C) IBM 2026
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Regression tests for main.settings.

settings.py reads the environment at import time and raises there, so we
exercise it by reloading the module with a patched environment.
"""

import importlib
import os
import sys

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

import main.settings


@pytest.fixture(autouse=True)
def restore_settings_module():
    """Reload main.settings with a valid environment after each test.

    A test that reloads settings.py while it raises leaves the module
    half-initialised, so reload it once more with a good environment to keep
    the rest of the suite unaffected. This forces the good state itself rather
    than relying on monkeypatch teardown order.
    """
    yield
    sys.modules.setdefault("pytest", pytest)
    previous_debug = os.environ.get("DEBUG")
    os.environ["DEBUG"] = "1"
    os.environ.pop("SETTINGS_AUTH_MECHANISM", None)
    os.environ.pop("DEFAULT_COMPUTE_PROFILE", None)
    os.environ.pop("DEFAULT_FUNCTION_SIZE_PROFILE", None)
    os.environ.pop("EVENT_STREAMS_BOOTSTRAP_SERVERS_EU_DE", None)
    os.environ.pop("EVENT_STREAMS_API_KEY_EU_DE", None)
    os.environ.pop("EVENT_STREAMS_ENABLED", None)
    os.environ.pop("EVENT_STREAMS_BOOTSTRAP_SERVERS", None)
    os.environ.pop("EVENT_STREAMS_API_KEY", None)
    try:
        importlib.reload(main.settings)
    finally:
        if previous_debug is None:
            os.environ.pop("DEBUG", None)
        else:
            os.environ["DEBUG"] = previous_debug


def test_missing_secret_key_fails_closed_when_debug_off(monkeypatch):
    """DEBUG off and no DJANGO_SECRET_KEY must fail closed at import time."""
    monkeypatch.setenv("DEBUG", "0")
    monkeypatch.delenv("DJANGO_SECRET_KEY", raising=False)
    # settings treats any pytest run as a test env (IS_TEST), which allows the
    # insecure fallback. Drop the marker so we hit the real production path.
    monkeypatch.delitem(sys.modules, "pytest", raising=False)

    with pytest.raises(ImproperlyConfigured):
        importlib.reload(main.settings)


def test_missing_secret_key_uses_fallback_when_debug_on(monkeypatch):
    """DEBUG on and no key loads fine and falls back to the dev secret."""
    monkeypatch.setenv("DEBUG", "1")
    monkeypatch.delenv("DJANGO_SECRET_KEY", raising=False)

    importlib.reload(main.settings)

    assert main.settings.SECRET_KEY
    assert main.settings.SECRET_KEY.startswith("django-insecure-")


def test_debug_defaults_to_off_when_unset(monkeypatch):
    """With DEBUG unset, DEBUG is falsy and LOG_LEVEL is INFO."""
    monkeypatch.delenv("DEBUG", raising=False)

    importlib.reload(main.settings)

    assert not main.settings.DEBUG
    assert main.settings.LOG_LEVEL == "INFO"


def test_debug_enabled_sets_debug_log_level(monkeypatch):
    """With DEBUG=1, DEBUG is truthy and LOG_LEVEL is DEBUG."""
    monkeypatch.setenv("DEBUG", "1")

    importlib.reload(main.settings)

    assert main.settings.DEBUG
    assert main.settings.LOG_LEVEL == "DEBUG"


class TestAuthMechanism:
    """Tests for SETTINGS_AUTH_MECHANISM handling in main.settings."""

    def test_unknown_mechanism_raises(self, monkeypatch):
        """A bogus mechanism fails closed with ImproperlyConfigured."""
        monkeypatch.setenv("SETTINGS_AUTH_MECHANISM", "bogus_mechanism")
        with pytest.raises(ImproperlyConfigured):
            importlib.reload(main.settings)

    def test_custom_token_resolves(self, monkeypatch):
        """The custom_token mechanism resolves without raising."""
        monkeypatch.setenv("SETTINGS_AUTH_MECHANISM", "custom_token")
        importlib.reload(main.settings)
        assert main.settings.SETTINGS_AUTH_MECHANISM == "custom_token"
        assert main.settings.DJR_DEFAULT_AUTHENTICATION_CLASSES == [
            "api.authentication.CustomTokenBackend",
        ]

    def test_mock_token_resolves(self, monkeypatch):
        """The mock_token mechanism resolves without raising."""
        monkeypatch.setenv("SETTINGS_AUTH_MECHANISM", "mock_token")
        importlib.reload(main.settings)
        assert main.settings.SETTINGS_AUTH_MECHANISM == "mock_token"
        assert main.settings.DJR_DEFAULT_AUTHENTICATION_CLASSES == [
            "api.authentication.MockTokenBackend",
        ]


def test_template_dirs_use_etc_gateway_not_tmp():
    """The extra template dir must be /etc/gateway/templates, never /tmp.

    The chart mounts the ray cluster template into /etc/gateway/templates. If
    that mount ever drifts back to a world-writable location like /tmp, any
    other process on the host could drop a malicious template into Django's
    search path. This test catches such a desync.
    """
    dirs = [str(path) for path in settings.TEMPLATES[0]["DIRS"]]
    assert "/etc/gateway/templates" in dirs
    assert "/tmp/templates" not in dirs


class TestComputeProfileSettings:
    """Tests for the compute profile settings read by _canonical_compute_profile."""

    def test_instance_family_prefix_is_stripped(self, monkeypatch):
        """A prefixed value is stored in the bare form the rest of the code looks up."""
        monkeypatch.setenv("DEFAULT_COMPUTE_PROFILE", "bx3d-24x120")
        monkeypatch.setenv("DEFAULT_FUNCTION_SIZE_PROFILE", "gx3d-24x120x1a100p")

        importlib.reload(main.settings)

        assert main.settings.DEFAULT_COMPUTE_PROFILE == "24x120"
        assert main.settings.DEFAULT_FUNCTION_SIZE_PROFILE == "24x120x1a100p"

    def test_a_value_that_is_not_a_profile_fails_closed(self, monkeypatch):
        """A malformed value stops the process at import rather than on the first run."""
        monkeypatch.setenv("DEFAULT_COMPUTE_PROFILE", "not-a-profile")

        with pytest.raises(ImproperlyConfigured):
            importlib.reload(main.settings)

    def test_an_empty_value_fails_closed(self, monkeypatch):
        """An empty environment variable is rejected, not treated as unset."""
        monkeypatch.setenv("DEFAULT_FUNCTION_SIZE_PROFILE", "")

        with pytest.raises(ImproperlyConfigured):
            importlib.reload(main.settings)


class TestEventStreamsRegions:
    """Tests for EVENT_STREAMS_REGIONS, discovered by _event_streams_regions() from
    EVENT_STREAMS_BOOTSTRAP_SERVERS_<REGION> / EVENT_STREAMS_API_KEY_<REGION> pairs."""

    def test_no_suffixed_vars_yields_empty_regions(self):
        importlib.reload(main.settings)

        assert main.settings.EVENT_STREAMS_REGIONS == {}

    def test_matched_pair_is_discovered(self, monkeypatch):
        monkeypatch.setenv("EVENT_STREAMS_BOOTSTRAP_SERVERS_EU_DE", "broker-eu:9093")
        monkeypatch.setenv("EVENT_STREAMS_API_KEY_EU_DE", "eu-key")

        importlib.reload(main.settings)

        assert main.settings.EVENT_STREAMS_REGIONS == {
            "eu-de": {"bootstrap_servers": "broker-eu:9093", "api_key": "eu-key", "user": "token"}
        }

    def test_custom_user_is_discovered(self, monkeypatch):
        monkeypatch.setenv("EVENT_STREAMS_BOOTSTRAP_SERVERS_EU_DE", "broker-eu:9093")
        monkeypatch.setenv("EVENT_STREAMS_API_KEY_EU_DE", "eu-key")
        monkeypatch.setenv("EVENT_STREAMS_USER_EU_DE", "custom-user")

        importlib.reload(main.settings)

        assert main.settings.EVENT_STREAMS_REGIONS["eu-de"]["user"] == "custom-user"

    def test_bootstrap_servers_without_matching_api_key_fails_closed(self, monkeypatch):
        """A typo'd or missing regional API key stops the process at import rather than on
        the first attempt to send an event to that region."""
        monkeypatch.setenv("EVENT_STREAMS_BOOTSTRAP_SERVERS_EU_DE", "broker-eu:9093")

        with pytest.raises(ImproperlyConfigured, match="missing EVENT_STREAMS_API_KEY_EU_DE"):
            importlib.reload(main.settings)


class TestEventStreamsMainCredentials:
    """Tests for the EVENT_STREAMS_ENABLED-gated requirement on the main region's credentials."""

    def test_missing_credentials_when_enabled_fails_closed(self, monkeypatch):
        """A deployment that turns Event Streams on must set the main credentials, and this must
        be caught at import time, not on the first attempt to construct a KafkaProducers."""
        monkeypatch.setenv("EVENT_STREAMS_ENABLED", "true")
        monkeypatch.delenv("EVENT_STREAMS_BOOTSTRAP_SERVERS", raising=False)
        monkeypatch.delenv("EVENT_STREAMS_API_KEY", raising=False)

        with pytest.raises(
            ImproperlyConfigured, match="EVENT_STREAMS_BOOTSTRAP_SERVERS and EVENT_STREAMS_API_KEY are required"
        ):
            importlib.reload(main.settings)

    def test_missing_credentials_when_disabled_is_fine(self, monkeypatch):
        """The vast majority of deployments never enable Event Streams and never set these, so
        their absence must not fail the boot."""
        monkeypatch.setenv("EVENT_STREAMS_ENABLED", "false")
        monkeypatch.delenv("EVENT_STREAMS_BOOTSTRAP_SERVERS", raising=False)
        monkeypatch.delenv("EVENT_STREAMS_API_KEY", raising=False)

        importlib.reload(main.settings)

        assert main.settings.EVENT_STREAMS_BOOTSTRAP_SERVERS is None

    def test_credentials_present_when_enabled_is_fine(self, monkeypatch):
        monkeypatch.setenv("EVENT_STREAMS_ENABLED", "true")
        monkeypatch.setenv("EVENT_STREAMS_BOOTSTRAP_SERVERS", "broker:9093")
        monkeypatch.setenv("EVENT_STREAMS_API_KEY", "key")

        importlib.reload(main.settings)

        assert main.settings.EVENT_STREAMS_BOOTSTRAP_SERVERS == "broker:9093"
