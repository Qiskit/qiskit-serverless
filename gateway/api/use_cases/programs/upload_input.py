"""Input dataclass for UploadFunctionUseCase."""

from dataclasses import dataclass
from typing import Any

from api.utils import parse_title_and_provider


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
    # None means "not sent", which leaves the stored catalog untouched. A sent
    # value replaces it wholesale.
    sizes: dict[str, str] | None = None
    default_size: str | None = None

    @classmethod
    def from_validated_data(cls, data: dict) -> "UploadFunctionInput":
        """Construct from a DRF serializer's validated_data, parsing provider/title convention."""
        title, provider = parse_title_and_provider(data.get("title", ""), data.get("provider"))
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
            sizes=data.get("sizes"),
            default_size=data.get("default_size"),
        )
