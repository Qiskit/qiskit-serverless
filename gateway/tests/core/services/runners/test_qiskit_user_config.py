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

"""Tests for the gateway-owned Qiskit user configuration file injected into job containers.

Covers both backends:
  - Fleets: the config is rendered into the fleet wrapper templates, which write it at
    container startup before launching the user function.
  - Ray: the config is written into the job working_dir and QISKIT_SETTINGS set in the
    runtime_env env_vars.
"""

import configparser
import json
import os
import tempfile
from unittest.mock import patch

from django.conf import settings
from django.template.loader import get_template


def _render_wrapper(template_name):
    """Render a fleet wrapper template the way FleetsRunner does."""
    return get_template(template_name).render(
        {
            "app_cmd": json.dumps(["python", "entrypoint.py"]),
            "qiskit_user_config": json.dumps(settings.QISKIT_USER_CONFIG),
        }
    )


def _config_writer(rendered):
    """Return the wrapper's ``_write_qiskit_user_config`` function, exec'd in isolation.

    The wrapper also runs ``_harden`` (libc syscalls, platform-specific) and spawns the
    user process, so we exec only the config-writer definition rather than the whole module.
    """
    marker = "def _write_qiskit_user_config():"
    start = rendered.index(marker)
    end = rendered.index("\n_write_qiskit_user_config()", start)
    namespace = {"os": os}
    exec(rendered[start:end], namespace)  # pylint: disable=exec-used
    return namespace["_write_qiskit_user_config"]


def _run_config_writer(rendered, env):
    """Run the wrapper's config-writer with ``env`` as the only environment."""
    with patch.dict(os.environ, env, clear=True):
        _config_writer(rendered)()


def test_user_config_contents_are_valid_ini_with_min_qpy_version():
    """QISKIT_USER_CONFIG is a valid INI file with [default] min_qpy_version."""
    parser = configparser.ConfigParser()
    parser.read_string(settings.QISKIT_USER_CONFIG)
    assert parser.has_section("default")
    assert parser.getint("default", "min_qpy_version") == settings.QISKIT_MIN_QPY_VERSION


def test_default_min_qpy_version_is_13():
    """The platform floor defaults to QPY 13."""
    assert settings.QISKIT_MIN_QPY_VERSION == 13


def test_custom_wrapper_compiles_and_writes_config():
    """The rendered custom wrapper is valid Python and writes the exact config to QISKIT_SETTINGS."""
    rendered = _render_wrapper("fleet_custom_job_wrapper.py")
    compile(rendered, "fleet_custom_job_wrapper.py", "exec")
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "nested", "settings.conf")
        _run_config_writer(rendered, {"QISKIT_SETTINGS": target})
        _assert_config_file(target)


def test_provider_wrapper_compiles_and_writes_config():
    """The rendered provider wrapper is valid Python and writes the exact config to QISKIT_SETTINGS."""
    rendered = _render_wrapper("fleet_provider_job_wrapper.py")
    compile(rendered, "fleet_provider_job_wrapper.py", "exec")
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "nested", "settings.conf")
        _run_config_writer(rendered, {"QISKIT_SETTINGS": target})
        _assert_config_file(target)


def _assert_config_file(target):
    """Assert the file at ``target`` is exactly the gateway-owned Qiskit config."""
    assert os.path.isfile(target)
    with open(target, encoding="utf-8") as handle:
        written = handle.read()
    assert written == settings.QISKIT_USER_CONFIG
    parser = configparser.ConfigParser()
    parser.read_string(written)
    assert parser.getint("default", "min_qpy_version") == settings.QISKIT_MIN_QPY_VERSION


def test_wrapper_config_writer_is_noop_without_env():
    """When QISKIT_SETTINGS is unset the writer returns early without crashing."""
    rendered = _render_wrapper("fleet_custom_job_wrapper.py")
    _run_config_writer(rendered, {})
