"""Input dataclass for UploadFunctionUseCase."""

from dataclasses import dataclass
from typing import Any


@dataclass
class UploadFunctionInput:  # pylint: disable=too-many-instance-attributes
    """Typed, pre-validated input for UploadFunctionUseCase."""

    title: str
    provider: str | None = None
    entrypoint: str | None = None
    artifact: Any = None
    image: str | None = None
    env_vars: str | None = None
    dependencies: str = "[]"
    runner: str = "ray"
    description: str | None = None
    version: str | None = None
    type: str | None = None
