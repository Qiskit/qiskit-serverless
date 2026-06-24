"""Input dataclass for UploadFunctionUseCase."""

from dataclasses import dataclass
from typing import Any

from core.models import Program as Function


def _parse_provider_and_title(provider_raw: str | None, title_raw: str) -> tuple[str | None, str]:
    if provider_raw:
        return provider_raw, title_raw
    parts = title_raw.split("/")
    if len(parts) == 1:
        return None, parts[0]
    return parts[0], parts[1]


@dataclass
class UploadFunctionInput:  # pylint: disable=too-many-instance-attributes
    """Typed, pre-validated input for UploadFunctionUseCase.

    title and provider are already parsed (no 'provider/title' convention here).
    """

    title: str
    provider: str | None = None
    entrypoint: str | None = None
    artifact: Any = None
    image: str | None = None
    env_vars: str | None = None
    dependencies: str | None = None
    runner: str | None = None
    description: str | None = None
    version: str | None = None
    type: str | None = None
    arguments_schema: str | None = None

    @classmethod
    def from_validated_data(cls, data: dict) -> "UploadFunctionInput":
        """Construct from a DRF serializer's validated_data, parsing provider/title convention."""
        provider, title = _parse_provider_and_title(data.get("provider"), data.get("title", ""))
        return cls(
            title=title,
            provider=provider,
            entrypoint=data.get("entrypoint"),
            artifact=data.get("artifact"),
            image=data.get("image"),
            env_vars=data.get("env_vars"),
            dependencies=data.get("dependencies"),
            runner=data.get("runner"),
            description=data.get("description"),
            version=data.get("version"),
            type=data.get("type"),
            arguments_schema=data.get("arguments_schema"),
        )
