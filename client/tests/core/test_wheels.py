# This code is a Qiskit project.
#
# (C) Copyright IBM 2026.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Tests for the install_uploaded_wheels runtime helper."""

import sys
from unittest.mock import patch

from qiskit_serverless.core.wheels import install_uploaded_wheels, DEFAULT_WHEELHOUSE


class TestInstallUploadedWheels:
    """Tests for install_uploaded_wheels()."""

    def test_no_op_when_no_wheels(self, tmp_path):
        """With an empty (or missing) wheelhouse, pip is not invoked."""
        with patch("qiskit_serverless.core.wheels.subprocess.run") as mock_run:
            result = install_uploaded_wheels(wheelhouse=str(tmp_path), target=str(tmp_path / "site"))

        mock_run.assert_not_called()
        assert result == str(tmp_path / "site")

    def test_installs_wheels_offline_with_no_deps(self, tmp_path):
        """pip is invoked offline (--no-index --no-deps) over the wheels in the wheelhouse."""
        wheelhouse = tmp_path / "wh"
        wheelhouse.mkdir()
        (wheelhouse / "mypkg-1.0-py3-none-any.whl").write_text("")
        (wheelhouse / "notawheel.txt").write_text("")
        target = tmp_path / "site"

        with patch("qiskit_serverless.core.wheels.subprocess.run") as mock_run, patch(
            "qiskit_serverless.core.wheels.site.addsitedir"
        ):
            install_uploaded_wheels(wheelhouse=str(wheelhouse), target=str(target))

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "--no-index" in cmd and "--no-deps" in cmd
        assert "--find-links" in cmd and str(wheelhouse) in cmd
        assert "--target" in cmd and str(target) in cmd
        # only the .whl is passed as a package, not the .txt
        assert any(arg.endswith("mypkg-1.0-py3-none-any.whl") for arg in cmd)
        assert not any(arg.endswith("notawheel.txt") for arg in cmd)
        assert mock_run.call_args[1].get("check") is True

    def test_prepends_target_to_sys_path(self, tmp_path):
        """After install, the target directory is importable (on sys.path)."""
        wheelhouse = tmp_path / "wh"
        wheelhouse.mkdir()
        (wheelhouse / "mypkg-1.0-py3-none-any.whl").write_text("")
        target = tmp_path / "site"
        target.mkdir()

        with patch("qiskit_serverless.core.wheels.subprocess.run"), patch(
            "qiskit_serverless.core.wheels.site.addsitedir"
        ):
            install_uploaded_wheels(wheelhouse=str(wheelhouse), target=str(target))

        assert sys.path[0] == str(target)
        sys.path.remove(str(target))  # cleanup

    def test_env_override_for_wheelhouse(self, tmp_path, monkeypatch):
        """QISKIT_FUNCTIONS_WHEELHOUSE overrides the default wheelhouse location."""
        wheelhouse = tmp_path / "custom"
        wheelhouse.mkdir()
        monkeypatch.setenv("QISKIT_FUNCTIONS_WHEELHOUSE", str(wheelhouse))

        with patch("qiskit_serverless.core.wheels.subprocess.run") as mock_run:
            install_uploaded_wheels(target=str(tmp_path / "site"))

        # empty custom wheelhouse -> no-op, but it looked at the overridden path
        mock_run.assert_not_called()

    def test_default_wheelhouse_constant(self):
        """The default wheelhouse is the Fleets function-user-data mount."""
        assert DEFAULT_WHEELHOUSE == "/function_user_data"
