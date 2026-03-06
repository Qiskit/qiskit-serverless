"""Runner enum for job execution backends."""

from enum import Enum


class Runner(str, Enum):
    """Enum representing available job execution backends."""

    GPU = "gpu"
    CPU = "cpu"
    FLEETS = "fleets"
