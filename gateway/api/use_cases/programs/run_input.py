"""Input dataclass for RunFunctionUseCase."""

from dataclasses import dataclass, field


@dataclass
class RunFunctionInput:  # pylint: disable=too-many-instance-attributes
    """Typed, pre-validated input for RunFunctionUseCase."""

    title: str
    provider_name: str | None
    arguments: str
    config_json: dict | None
    compute_profile: str | None
    channel: str
    token: str
    instance: str | None
    account_id: str | None
    carrier: dict = field(default_factory=dict)
