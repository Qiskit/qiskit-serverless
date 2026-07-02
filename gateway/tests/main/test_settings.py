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

"""Regression tests for main.settings ALLOWED_HOSTS handling."""

import importlib
import sys
from unittest.mock import patch

import pytest
from django.core.exceptions import ImproperlyConfigured


@pytest.fixture(autouse=True)
def restore_main_settings():
    """Reload main.settings with a valid env after each test.

    Reloading the module runs settings.py top to bottom and mutates the
    imported module in place, so leave it in a clean, test-friendly state
    (pytest is in sys.modules, so IS_TEST is True) and other tests are not
    polluted by a half-initialized module.
    """
    yield
    assert "pytest" in sys.modules
    import main.settings

    importlib.reload(main.settings)


def test_allowed_hosts_required_when_debug_off(monkeypatch):
    """Unset ALLOWED_HOSTS with DEBUG off fails closed in production."""
    monkeypatch.setenv("DEBUG", "0")
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)

    import main.settings

    # Hide pytest from sys.modules only for this reload so IS_TEST is False
    # and the production guard is actually exercised.
    with patch.dict("sys.modules"):
        sys.modules.pop("pytest", None)
        with pytest.raises(ImproperlyConfigured):
            importlib.reload(main.settings)


def test_allowed_hosts_wildcard_when_debug_on(monkeypatch):
    """Unset ALLOWED_HOSTS with DEBUG on defaults to the wildcard."""
    monkeypatch.setenv("DEBUG", "1")
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)

    import main.settings

    importlib.reload(main.settings)

    assert main.settings.ALLOWED_HOSTS == ["*"]


def test_allowed_hosts_uses_set_value(monkeypatch):
    """A set ALLOWED_HOSTS value is used as-is, split on commas."""
    monkeypatch.setenv("DEBUG", "0")
    monkeypatch.setenv("ALLOWED_HOSTS", "example.com")

    import main.settings

    importlib.reload(main.settings)

    assert main.settings.ALLOWED_HOSTS == ["example.com"]
