"""Regression tests for the DJANGO_SECRET_KEY fail-closed behaviour.

settings.py reads the environment at import time and raises there, so we
exercise it by reloading the module with a patched environment.
"""

import importlib
import os
import sys

import pytest
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
