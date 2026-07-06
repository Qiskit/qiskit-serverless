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

"""Tests for main.settings."""

import importlib
import os

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

import main.settings


@pytest.fixture(autouse=True)
def restore_settings():
    """Reload main.settings with a clean default env after each test.

    The tests reload the settings module with a patched environment, so clear
    the overrides and reload once more on teardown to leave the module in a
    good state and avoid polluting the rest of the suite. Clearing the env
    vars here (instead of relying on monkeypatch) keeps the teardown
    order-independent.
    """
    yield
    os.environ.pop("DEBUG", None)
    os.environ.pop("SETTINGS_AUTH_MECHANISM", None)
    importlib.reload(main.settings)


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
