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

"""Unit tests for the ComputeProfile value object and the catalog formatter."""

from qiskit_serverless import ComputeProfile
from qiskit_serverless.core.compute_profile import ComputeProfileList, format_profiles


def _cp(compute_profile_id, cpu, memory, gpu=None):
    return ComputeProfile(compute_profile_id=compute_profile_id, cpu=cpu, memory=memory, gpu=gpu)


class TestComputeProfileObject:
    """Construction, serialization, and repr."""

    def test_from_json_keeps_known_fields_and_ignores_extras(self):
        """from_json builds from the endpoint payload and tolerates unknown keys (e.g. name)."""
        profile = ComputeProfile.from_json(
            {"compute_profile_id": "24x120", "cpu": "24", "memory": "120", "gpu": None, "name": "s"}
        )
        assert profile == _cp("24x120", "24", "120")

    def test_str_is_the_id_so_it_serializes_into_a_sizes_map(self):
        """str() is the compute_profile_id, i.e. the wire form used in a sizes_map."""
        assert str(_cp("24x120x1l40s", "24", "120", gpu="1l40s")) == "24x120x1l40s"

    def test_repr_reads_the_specs(self):
        """repr shows the id and the CPU / memory / GPU specs."""
        assert repr(_cp("24x120", "24", "120")) == "ComputeProfile('24x120', 24 vCPU / 120 GB)"
        assert repr(_cp("24x120x1l40s", "24", "120", gpu="1l40s")) == (
            "ComputeProfile('24x120x1l40s', 24 vCPU / 120 GB / 1l40s)"
        )


class TestFormatProfiles:
    """format_profiles renders the ordered, aligned catalog."""

    def test_orders_cpu_only_first_then_gpu_by_memory_and_aligns(self):
        """CPU-only first, then GPU by increasing memory (model ignored); id column padded."""
        text = format_profiles(
            [
                _cp("20x320x2a100", "20", "320", gpu="2a100"),
                _cp("24x120", "24", "120"),
                _cp("24x120x1l40s", "24", "120", gpu="1l40s"),
            ]
        )
        assert text == (
            "24x120        (24 vCPU / 120 GB)\n"
            "24x120x1l40s  (24 vCPU / 120 GB / 1l40s)\n"
            "20x320x2a100  (20 vCPU / 320 GB / 2a100)"
        )

    def test_empty_is_empty_string(self):
        """No profiles renders as an empty string."""
        assert format_profiles([]) == ""


class TestComputeProfileList:
    """The list subclass prints as the formatted catalog but is still a list."""

    def test_prints_as_the_formatted_catalog(self):
        """str()/repr of the list render the aligned table, so print() needs no iteration."""
        profiles = ComputeProfileList([_cp("24x120", "24", "120"), _cp("24x120x1l40s", "24", "120", gpu="1l40s")])
        rendered = format_profiles(profiles)
        assert str(profiles) == rendered
        assert repr(profiles) == rendered

    def test_behaves_like_a_list(self):
        """Indexing, len, and membership work as on a plain list."""
        a, b = _cp("24x120", "24", "120"), _cp("24x120x1l40s", "24", "120", gpu="1l40s")
        profiles = ComputeProfileList([a, b])
        assert len(profiles) == 2
        assert profiles[0] is a
        assert b in profiles
