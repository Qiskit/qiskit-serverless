"""Quantum serverless."""

from importlib_metadata import version as metadata_version, PackageNotFoundError

from .core import QuantumServerless, Cluster, remote, get, put

try:
    __version__ = metadata_version("quantum_serverless")
except PackageNotFoundError:  # pragma: no cover
    # package is not installed
    pass
