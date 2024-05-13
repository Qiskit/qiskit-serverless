"""QS toolkit project."""

from importlib_metadata import version as metadata_version, PackageNotFoundError


try:
    __version__ = metadata_version("qiskit_serverless_tools")
except PackageNotFoundError:  # pragma: no cover
    # package is not installed
    pass
