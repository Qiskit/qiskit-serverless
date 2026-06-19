"""Input dataclass for UploadFunctionUseCase."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class UploadFunctionInput:
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

    @classmethod
    def from_validated_data(cls, data: dict) -> "UploadFunctionInput":
        return cls(
            title=data.get("title", ""),
            provider=data.get("provider"),
            entrypoint=data.get("entrypoint"),
            artifact=data.get("artifact"),
            image=data.get("image"),
            env_vars=data.get("env_vars"),
            dependencies=data.get("dependencies", "[]"),
            runner=data.get("runner", "ray"),
            description=data.get("description"),
            version=data.get("version"),
            type=data.get("type"),
        )
