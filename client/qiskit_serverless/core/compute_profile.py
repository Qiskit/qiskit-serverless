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
===============================================================
Compute profile (:mod:`qiskit_serverless.core.compute_profile`)
===============================================================

.. currentmodule:: qiskit_serverless.core.compute_profile

.. autosummary::
    :toctree: ../stubs/

    ComputeProfile
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional


def _as_number(value: str) -> float:
    """Parse a dimension field for sorting; non-numeric values sort last."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("inf")


@dataclass(frozen=True)
class ComputeProfile:
    """One entry of a deployment's compute-profile catalog.

    Obtain these from :meth:`ServerlessClient.compute_profiles` (the catalog) or
    :meth:`ServerlessClient.compute_profile` (a single validated one); both are documented on
    the client. A profile can be used directly as a ``sizes_map`` value when uploading a
    function — it serializes to its :attr:`compute_profile_id`, so it is interchangeable with
    that plain string.

    Attributes:
        compute_profile_id: the deployment's identifier (e.g. ``"24x120x1l40s"``); the value
            that travels on the wire in a ``sizes_map``.
        cpu: number of vCPUs (e.g. ``"24"``).
        memory: memory in GB (e.g. ``"120"``).
        gpu: GPU allocation as count + model (e.g. ``"1l40s"``); ``None`` for a CPU-only profile.
    """

    compute_profile_id: str
    cpu: str
    memory: str
    gpu: Optional[str] = None

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "ComputeProfile":
        """Build a ``ComputeProfile`` from one entry of the compute-profiles endpoint payload."""
        field_names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in field_names})

    def specs(self) -> str:
        """Human-readable specs, e.g. ``24 vCPU / 120 GB / 1l40s`` (GPU part omitted if none)."""
        text = f"{self.cpu} vCPU / {self.memory} GB"
        if self.gpu:
            text += f" / {self.gpu}"
        return text

    def __str__(self) -> str:
        # The id is the wire form; str() is what JSON-serializing a sizes_map value lands on.
        return self.compute_profile_id

    def __repr__(self) -> str:
        return f"ComputeProfile('{self.compute_profile_id}', {self.specs()})"


class ComputeProfileList(List["ComputeProfile"]):
    """A plain list of profiles that prints as the aligned catalog.

    Behaves exactly like ``list`` (indexing, iteration, ``len``, membership); only its
    ``str``/``repr`` differ, so ``print(client.compute_profiles())`` shows the formatted table
    without the caller iterating.
    """

    def __str__(self) -> str:
        return format_profiles(self)

    def __repr__(self) -> str:
        return format_profiles(self)


def _sorted_for_display(profiles: Iterable["ComputeProfile"]) -> List["ComputeProfile"]:
    """CPU-only profiles first, then GPU profiles by increasing memory (model ignored)."""
    return sorted(
        profiles,
        key=lambda p: (bool(p.gpu), _as_number(p.memory), _as_number(p.cpu), p.compute_profile_id),
    )


def format_profiles(profiles: Iterable["ComputeProfile"]) -> str:
    """Render profiles as aligned ``id  (specs)`` lines, ordered for display.

    Shared by the printable catalog list and the "no match" error. The id column is padded to
    the widest id so the spec blocks line up.
    """
    ordered = _sorted_for_display(profiles)
    if not ordered:
        return ""
    id_width = max(len(p.compute_profile_id) for p in ordered)
    return "\n".join(f"{p.compute_profile_id.ljust(id_width)}  ({p.specs()})" for p in ordered)
