"""Input dataclass for RunFunctionUseCase."""

from dataclasses import dataclass, field


@dataclass
class RunFunctionInput:  # pylint: disable=too-many-instance-attributes
    """Typed, pre-validated input for RunFunctionUseCase."""

    title: str
    provider_name: str | None
    arguments: str
    config_data: dict | None
    # Deprecated: prefer ``function_size``. Expected already in bare (prefix-less)
    # canonical form; the view normalizes the raw client value before building
    # this input.
    compute_profile: str | None
    # A declared size label (e.g. "m"), already normalized (strip+casefold) by
    # the view. Resolved to a compute profile through the function's FunctionSize
    # catalog in the use case. Replaces ``compute_profile`` as the run input.
    function_size: str | None
    channel: str
    token: str
    instance: str | None
    account_id: str | None
    carrier: dict = field(default_factory=dict)
