"""Regression tests for main.settings defaults."""

import importlib
import pytest
import main.settings
from django.conf import settings


@pytest.fixture(autouse=True)
def restore_settings(monkeypatch):
    """Reload main.settings with a clean default env after each test.

    The tests below reload the settings module with a patched environment,
    so we reload it once more on teardown to leave the module clean and
    avoid polluting other tests in the suite.
    """
    yield
    monkeypatch.delenv("DEBUG", raising=False)
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
