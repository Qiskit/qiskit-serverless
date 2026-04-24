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

"""
Compute Profile Parser for Code Engine Fleets.

Parses Code Engine compute profile names to extract CPU, memory, and GPU specs.
Profile pattern: ``[type]-[cpu]x[memory]`` or ``[type]-[cpu]x[memory]x[gpu_count][gpu_type]``

Examples::

    ComputeProfileParser.get_cpu("gx3d-24x120x1a100p")   # 24
    ComputeProfileParser.get_memory("gx3d-24x120x1a100p") # "120G"
    ComputeProfileParser.get_gpu_config("gx3d-24x120x1a100p")
    # {"scale_gpu": {"preferences": [{"family": "a100", "allocation": "1"}]}}
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger("FleetsRunner")

# Map Code Engine GPU suffixes to the short family names expected by the Fleets API.
_GPU_TYPE_MAP: dict[str, str] = {
    "a100p": "a100",
    "v100p": "v100",
    "t4p": "t4",
    "l40sp": "l40s",
    "h100p": "h100",
    "h200p": "h200",
    "a100": "a100",
    "v100": "v100",
    "t4": "t4",
    "l40s": "l40s",
    "h100": "h100",
    "h200": "h200",
}

# Pattern: [type]-[cpu]x[memory] or [type]-[cpu]x[memory]x[gpu_count][gpu_type]
_PROFILE_RE = re.compile(r"^([a-z]+\d+[a-z]?)-(\d+)x(\d+)(?:x(\d+)([a-z0-9]+p?))?$")


class ComputeProfileParser:
    """Parser for Code Engine compute profile names."""

    @staticmethod
    def parse(compute_profile: str) -> dict | None:
        """Parse a compute profile name and return its specifications.

        Args:
            compute_profile: Profile name, e.g. ``"gx3d-24x120x1a100p"`` or ``"cx3d-4x16"``.

        Returns:
            Dict with ``cpu``, ``memory``, ``gpu_count``, ``gpu_type``, ``is_gpu``,
            or ``None`` if the format is invalid or the GPU suffix is unknown.
        """
        m = _PROFILE_RE.match(compute_profile.lower())
        if not m:
            logger.warning("Invalid compute profile format: %s", compute_profile)
            return None

        _, cpu_str, mem_str, gpu_count_str, gpu_suffix = m.groups()
        cpu = int(cpu_str)
        memory = int(mem_str)

        if gpu_count_str is None:
            return {"cpu": cpu, "memory": memory, "gpu_count": 0, "gpu_type": None, "is_gpu": False}

        gpu_type = _GPU_TYPE_MAP.get(gpu_suffix)
        if gpu_type is None:
            logger.warning("Unknown GPU suffix %r in compute profile: %s", gpu_suffix, compute_profile)
            return None

        return {
            "cpu": cpu,
            "memory": memory,
            "gpu_count": int(gpu_count_str),
            "gpu_type": gpu_type,
            "is_gpu": True,
        }

    @staticmethod
    def get_cpu(compute_profile: str) -> int | None:
        """Return the CPU count from a compute profile, or ``None`` if invalid.

        Args:
            compute_profile: Profile name.

        Returns:
            CPU count or ``None``.
        """
        parsed = ComputeProfileParser.parse(compute_profile)
        return parsed["cpu"] if parsed else None

    @staticmethod
    def get_memory(compute_profile: str) -> str | None:
        """Return the memory from a compute profile as a CE-formatted string (e.g. ``"120G"``).

        Args:
            compute_profile: Profile name.

        Returns:
            Memory string with ``G`` suffix, or ``None`` if invalid.
        """
        parsed = ComputeProfileParser.parse(compute_profile)
        return f"{parsed['memory']}G" if parsed else None

    @staticmethod
    def get_gpu_config(compute_profile: str) -> dict | None:
        """Return the GPU configuration dict for the Code Engine Fleets API, or ``None``.

        Args:
            compute_profile: Profile name.

        Returns:
            ``{"scale_gpu": {"preferences": [{"family": ..., "allocation": ...}]}}``
            or ``None`` if the profile has no GPU.
        """
        parsed = ComputeProfileParser.parse(compute_profile)
        if not parsed or not parsed["is_gpu"]:
            return None
        return {
            "scale_gpu": {
                "preferences": [
                    {
                        "family": parsed["gpu_type"],
                        "allocation": str(parsed["gpu_count"]),
                    }
                ]
            }
        }
