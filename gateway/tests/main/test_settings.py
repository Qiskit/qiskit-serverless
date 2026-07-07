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
