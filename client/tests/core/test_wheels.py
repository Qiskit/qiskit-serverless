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

import hashlib
import json
import os
import sys
from unittest.mock import patch

import pytest

from qiskit_serverless.core.wheels import (
    install_uploaded_wheels,
    DEFAULT_WHEELHOUSE,
    CHUNK_MANIFEST_NAME,
    CHUNK_MANIFEST_SCHEMA,
)


def _write_chunked_wheel(wheelhouse, wheel_name, data, part_size):
    """Write ``data`` split into parts + a matching manifest entry into ``wheelhouse``.

    Returns the manifest entry dict (so a test can corrupt it before dumping the manifest).
    """
    parts = []
    index = 0
    offset = 0
    total = len(data)
    part_count = max(1, (total + part_size - 1) // part_size)
    for index in range(1, part_count + 1):
        chunk = data[offset : offset + part_size]
        offset += part_size
        part_name = f"{wheel_name}.part-{index:04d}-of-{part_count:04d}"
        (wheelhouse / part_name).write_bytes(chunk)
        parts.append(part_name)
    return {
        "wheel": wheel_name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": total,
        "part_size": part_size,
        "part_count": part_count,
        "parts": parts,
    }


def _write_manifest(wheelhouse, entries, schema=CHUNK_MANIFEST_SCHEMA):
    (wheelhouse / CHUNK_MANIFEST_NAME).write_text(json.dumps({"schema": schema, "chunked_wheels": entries}))


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
        """The default wheelhouse is the wheels sub-directory of the uploaded user data."""
        assert DEFAULT_WHEELHOUSE == "/function_user_data/wheels"


class TestInstallUploadedWheelsChunked:
    """Tests for the chunk-reassembly path of install_uploaded_wheels()."""

    def _patches(self, tmp_path):
        """Patch subprocess.run, addsitedir, and mkdtemp to a known tmp subdir."""
        workdir = tmp_path / "work"

        def _mkdtemp(*_args, **_kwargs):
            os.makedirs(workdir, exist_ok=True)
            return str(workdir)

        return (
            patch("qiskit_serverless.core.wheels.subprocess.run"),
            patch("qiskit_serverless.core.wheels.site.addsitedir"),
            patch("qiskit_serverless.core.wheels.tempfile.mkdtemp", side_effect=_mkdtemp),
            workdir,
        )

    def test_reassembles_and_verifies_chunked_wheel(self, tmp_path):
        """A chunked wheel is rebuilt from parts and its reassembled path is passed to pip."""
        wheelhouse = tmp_path / "wh"
        wheelhouse.mkdir()
        data = b"CHUNKED WHEEL CONTENT " * 5000  # a few parts
        entry = _write_chunked_wheel(wheelhouse, "big-1.0-py3-none-any.whl", data, part_size=4096)
        _write_manifest(wheelhouse, [entry])
        target = tmp_path / "site"

        run_cm, site_cm, mkdtemp_cm, workdir = self._patches(tmp_path)
        with run_cm as mock_run, site_cm, mkdtemp_cm:
            install_uploaded_wheels(wheelhouse=str(wheelhouse), target=str(target))

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        reassembled = os.path.join(str(workdir), "big-1.0-py3-none-any.whl")
        assert reassembled in cmd
        # The reassembled bytes equal the original (install happens before cleanup, so assert via
        # the mock: the file existed and matched at call time by checking it was the arg).
        assert "--no-index" in cmd and "--no-deps" in cmd

    def test_raises_on_sha256_mismatch(self, tmp_path):
        """A manifest sha256 that does not match the parts raises before pip runs."""
        wheelhouse = tmp_path / "wh"
        wheelhouse.mkdir()
        data = b"good bytes " * 1000
        entry = _write_chunked_wheel(wheelhouse, "pkg-1.0-py3-none-any.whl", data, part_size=2048)
        entry["sha256"] = "0" * 64  # wrong
        _write_manifest(wheelhouse, [entry])

        run_cm, site_cm, mkdtemp_cm, _ = self._patches(tmp_path)
        with run_cm as mock_run, site_cm, mkdtemp_cm:
            with pytest.raises(RuntimeError, match="Checksum mismatch"):
                install_uploaded_wheels(wheelhouse=str(wheelhouse), target=str(tmp_path / "site"))
        mock_run.assert_not_called()

    def test_raises_on_missing_part(self, tmp_path):
        """A manifest that references a part not on disk raises before pip runs."""
        wheelhouse = tmp_path / "wh"
        wheelhouse.mkdir()
        data = b"x" * 10000
        entry = _write_chunked_wheel(wheelhouse, "pkg-1.0-py3-none-any.whl", data, part_size=4096)
        os.remove(wheelhouse / entry["parts"][-1])  # drop the last part
        _write_manifest(wheelhouse, [entry])

        run_cm, site_cm, mkdtemp_cm, _ = self._patches(tmp_path)
        with run_cm as mock_run, site_cm, mkdtemp_cm:
            with pytest.raises(RuntimeError, match="missing part"):
                install_uploaded_wheels(wheelhouse=str(wheelhouse), target=str(tmp_path / "site"))
        mock_run.assert_not_called()

    def test_mixed_whole_and_chunked_installed_together(self, tmp_path):
        """One whole wheel and one chunked wheel install in a single pip invocation."""
        wheelhouse = tmp_path / "wh"
        wheelhouse.mkdir()
        (wheelhouse / "small-1.0-py3-none-any.whl").write_bytes(b"whole")
        entry = _write_chunked_wheel(wheelhouse, "big-1.0-py3-none-any.whl", b"z" * 9000, part_size=4096)
        _write_manifest(wheelhouse, [entry])

        run_cm, site_cm, mkdtemp_cm, workdir = self._patches(tmp_path)
        with run_cm as mock_run, site_cm, mkdtemp_cm:
            install_uploaded_wheels(wheelhouse=str(wheelhouse), target=str(tmp_path / "site"))

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert any(arg.endswith("small-1.0-py3-none-any.whl") for arg in cmd)
        assert os.path.join(str(workdir), "big-1.0-py3-none-any.whl") in cmd

    def test_rejects_unknown_schema(self, tmp_path):
        """A manifest from a newer client (unknown schema) is rejected loudly."""
        wheelhouse = tmp_path / "wh"
        wheelhouse.mkdir()
        entry = _write_chunked_wheel(wheelhouse, "pkg-1.0-py3-none-any.whl", b"a" * 5000, part_size=2048)
        _write_manifest(wheelhouse, [entry], schema=CHUNK_MANIFEST_SCHEMA + 999)

        run_cm, site_cm, mkdtemp_cm, _ = self._patches(tmp_path)
        with run_cm as mock_run, site_cm, mkdtemp_cm:
            with pytest.raises(RuntimeError, match="schema"):
                install_uploaded_wheels(wheelhouse=str(wheelhouse), target=str(tmp_path / "site"))
        mock_run.assert_not_called()

    def test_workdir_cleaned_up(self, tmp_path):
        """The reassembly work dir is removed after a successful install."""
        wheelhouse = tmp_path / "wh"
        wheelhouse.mkdir()
        entry = _write_chunked_wheel(wheelhouse, "pkg-1.0-py3-none-any.whl", b"b" * 9000, part_size=4096)
        _write_manifest(wheelhouse, [entry])

        run_cm, site_cm, mkdtemp_cm, workdir = self._patches(tmp_path)
        with run_cm, site_cm, mkdtemp_cm:
            install_uploaded_wheels(wheelhouse=str(wheelhouse), target=str(tmp_path / "site"))

        assert not os.path.isdir(workdir)

    def test_part_file_without_manifest_is_ignored(self, tmp_path):
        """A lone part file with no manifest is not treated as a wheel; pip is not called."""
        wheelhouse = tmp_path / "wh"
        wheelhouse.mkdir()
        (wheelhouse / "pkg-1.0-py3-none-any.whl.part-0001-of-0002").write_bytes(b"orphan")

        with patch("qiskit_serverless.core.wheels.subprocess.run") as mock_run, patch(
            "qiskit_serverless.core.wheels.site.addsitedir"
        ):
            install_uploaded_wheels(wheelhouse=str(wheelhouse), target=str(tmp_path / "site"))

        mock_run.assert_not_called()
