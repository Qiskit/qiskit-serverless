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

"""
Runtime helper for installing user-uploaded wheels
===================================================

Install wheels that were uploaded to a function's file area (see
``client.add_wheels()``) from the function's entrypoint, so they are importable
during execution.
"""

import hashlib
import json
import os
import shutil
import site
import subprocess
import sys
import tempfile
from typing import List, Optional

# Where a function's uploaded user files are mounted inside the runtime container.
FUNCTION_USER_DATA = "/function_user_data"

# Sub-directory of the function's file area that ``client.add_wheels()`` uploads into, and that
# this helper installs from. Keeping wheels in their own directory keeps them separate from any
# other files a function uploads. The client passes this name to the files API as the sub-path.
WHEELS_SUBDIR = "wheels"

# Default directory to install wheels from: the ``wheels`` sub-directory of the uploaded user data.
DEFAULT_WHEELHOUSE = f"{FUNCTION_USER_DATA}/{WHEELS_SUBDIR}"

# Optional environment override, in case the mount location is relocated by ops.
ENV_WHEELHOUSE = "QISKIT_FUNCTIONS_WHEELHOUSE"

# Where installed wheels are placed and added to the import path.
DEFAULT_TARGET = "/tmp/site"

# Wheel chunking (shared between the client's add_wheels() and this runtime helper).
# A wheel too large to upload in one request is split into parts named
# ``<wheel>.whl.part-0001-of-0004``. The ``.part-`` infix is the detection substring, and a part
# name never ends in ``.whl``, so the whole-wheel scan below skips parts automatically. The parts
# and a manifest recording their order and the original wheel's sha256 live in the wheels dir.
CHUNK_PART_INFIX = ".part-"
CHUNK_MANIFEST_NAME = ".wheel-chunks-manifest.json"
CHUNK_MANIFEST_SCHEMA = 1

# Block size for streaming reassembly and hashing (1 MiB).
_CHUNK_IO_BLOCK = 1024 * 1024


def install_uploaded_wheels(
    wheelhouse: Optional[str] = None,
    target: str = DEFAULT_TARGET,
) -> str:
    """Install wheels uploaded to this function and make them importable.

    Call this at the top of your entrypoint, before importing the uploaded packages::

        from qiskit_serverless import install_uploaded_wheels
        install_uploaded_wheels()
        import mypkg  # now importable

    It runs ``pip install --no-index --no-deps --find-links <wheelhouse> --target <target>``
    over every wheel in ``wheelhouse`` and prepends ``target`` to ``sys.path``. ``--no-index``
    keeps the install fully offline, and ``--no-deps`` is required: otherwise ``--no-index`` makes
    pip try to satisfy dependencies that are already baked into the image (numpy, qiskit, ...) from
    the wheelhouse and fail. Build your wheels with everything they need, or rely on what the image
    already ships (see ``client.dependencies_versions()``).

    Large wheels that ``add_wheels()`` had to split for upload are transparently reassembled
    from their parts here and verified against a sha256 manifest before installation; a missing
    part or a checksum mismatch raises rather than installing a corrupt wheel. Reassembly happens
    in a temporary directory (the uploaded wheels directory is read-only at runtime) that is
    removed after the install.

    Note: wheels are installed on every execution. If no wheels are present this is a no-op.

    Args:
        wheelhouse: directory to install wheels from. Defaults to the ``QISKIT_FUNCTIONS_WHEELHOUSE``
            environment variable if set, otherwise ``/function_user_data`` (where uploads land).
        target: directory to install into and prepend to ``sys.path``. Defaults to ``/tmp/site``.

    Returns:
        The ``target`` directory the wheels were installed into.
    """
    wheelhouse = wheelhouse or os.environ.get(ENV_WHEELHOUSE) or DEFAULT_WHEELHOUSE

    names = os.listdir(wheelhouse) if os.path.isdir(wheelhouse) else []
    # Whole wheels: uploaded in one piece. Parts never end in ".whl", so they are excluded here;
    # the explicit CHUNK_PART_INFIX check documents that intent.
    whole_wheels = [n for n in names if n.endswith(".whl") and CHUNK_PART_INFIX not in n]
    manifest_path = os.path.join(wheelhouse, CHUNK_MANIFEST_NAME)
    has_manifest = os.path.isfile(manifest_path)

    if not whole_wheels and not has_manifest:
        # Nothing to install; still ensure target is importable if it already exists.
        _prepend_to_path(target)
        return target

    workdir: Optional[str] = None
    try:
        install_paths: List[str] = [os.path.join(wheelhouse, name) for name in whole_wheels]

        if has_manifest:
            workdir = tempfile.mkdtemp(prefix="qs-wheels-")
            install_paths.extend(_reassemble_chunked_wheels(wheelhouse, manifest_path, workdir))

        if not install_paths:
            _prepend_to_path(target)
            return target

        os.makedirs(target, exist_ok=True)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                "--find-links",
                wheelhouse,
                "--target",
                target,
                *install_paths,
            ],
            check=True,
        )
    finally:
        if workdir is not None:
            # The reassembled wheels are only needed for the duration of the pip install; pip has
            # copied the installed package into ``target``. Reclaim the /tmp space.
            shutil.rmtree(workdir, ignore_errors=True)

    _prepend_to_path(target)
    return target


def _reassemble_chunked_wheels(wheelhouse: str, manifest_path: str, workdir: str) -> List[str]:
    """Rebuild each chunked wheel from its parts into ``workdir`` and verify it.

    Reads the chunk manifest, concatenates each wheel's parts in the recorded order, and checks
    the reassembled file against the manifest's sha256 before it is handed to pip. Raises loudly
    (so the failure surfaces in the entrypoint) if the manifest schema is unknown, a part is
    missing, or a checksum does not match.

    Returns the list of reassembled wheel paths (under ``workdir``).
    """
    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    schema = manifest.get("schema")
    if schema != CHUNK_MANIFEST_SCHEMA:
        raise RuntimeError(
            f"Unsupported wheel-chunk manifest schema {schema!r} (this runtime understands "
            f"{CHUNK_MANIFEST_SCHEMA}). Upgrade qiskit-serverless in the function image."
        )

    return [_reassemble_one(wheelhouse, workdir, entry) for entry in manifest.get("chunked_wheels", [])]


def _reassemble_one(wheelhouse: str, workdir: str, entry: dict) -> str:
    """Rebuild and verify a single chunked wheel from its manifest entry; return its path."""
    wheel_name = entry["wheel"]
    parts = entry["parts"]

    missing = [p for p in parts if not os.path.isfile(os.path.join(wheelhouse, p))]
    if missing:
        raise RuntimeError(
            f"Cannot reassemble wheel '{wheel_name}': missing part(s) {missing}. "
            "Re-upload the wheel with client.add_wheels()."
        )

    out_path = os.path.join(workdir, wheel_name)
    digest = hashlib.sha256()
    with open(out_path, "wb") as out:
        for part in parts:
            with open(os.path.join(wheelhouse, part), "rb") as src:
                while True:
                    block = src.read(_CHUNK_IO_BLOCK)
                    if not block:
                        break
                    out.write(block)
                    digest.update(block)

    actual = digest.hexdigest()
    if entry.get("sha256") != actual:
        os.remove(out_path)
        raise RuntimeError(
            f"Checksum mismatch for reassembled wheel '{wheel_name}': expected {entry.get('sha256')}, "
            f"got {actual}. The uploaded parts are corrupt or incomplete; re-upload the wheel."
        )

    return out_path


def _prepend_to_path(target: str) -> None:
    """Make packages installed under ``target`` importable in this process."""
    if os.path.isdir(target) and target not in sys.path:
        sys.path.insert(0, target)
        # Process .pth files and namespace packages the install may have created.
        site.addsitedir(target)
