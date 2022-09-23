"""Quantum serverless."""

from importlib_metadata import version as metadata_version, PackageNotFoundError

from .core import Provider, run_qiskit_remote, get, put
from .quantum_serverless import QuantumServerless

try:
    __version__ = metadata_version("quantum_serverless")
except PackageNotFoundError:  # pragma: no cover
    # package is not installed
    pass
