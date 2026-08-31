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

"""Compute profile normalization.

A compute profile may arrive with an IBM Cloud instance-family prefix
(e.g. ``bx3d-24x120``, ``gx3d-24x120x1a100p``). The prefix selects nothing we
use: sizing is driven entirely by the ``{cpu}x{memory}[x{count}{model}]``
resource part. The bare resource id is the canonical form we persist, look up
(``ComputeProfile`` primary key), bill on, and echo back to clients, so we strip
the prefix once, as early as possible.
"""

import re
from typing import Optional

# Optional instance-family prefix: lowercase letters, a digit, then more
# alphanumerics, ended by a hyphen (e.g. "bx3d-", "gx3d-", "cx3d-").
_PREFIX_RE = re.compile(r"^[a-z]+\d[a-z\d]*-(.+)$")


def normalize_compute_profile(value: Optional[str]) -> Optional[str]:
    """Return the bare (prefix-less) compute profile id.

    Strips an optional instance-family prefix. Idempotent: an already-bare
    value is returned unchanged. ``None`` or empty input returns ``None``.

    Examples:
        ``bx3d-24x120`` -> ``24x120``
        ``gx3d-24x120x1a100p`` -> ``24x120x1a100p``
        ``24x120`` -> ``24x120``
    """
    if not value:
        return None
    match = _PREFIX_RE.match(value)
    return match.group(1) if match else value
