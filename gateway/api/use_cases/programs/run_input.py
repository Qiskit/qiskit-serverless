"""Input dataclass for RunFunctionUseCase."""

from dataclasses import dataclass, field


@dataclass
class RunFunctionInput:  # pylint: disable=too-many-instance-attributes
    """Typed, pre-validated input for RunFunctionUseCase."""

    title: str
    provider_name: str | None
    arguments: str
    config_data: dict | None
    # A declared size label (e.g. "m"), already normalized (strip+casefold) by
    # the view. Resolved to a compute profile through the function's FunctionSize
    # catalog in the use case.
    function_size: str | None
    channel: str
    token: str
    instance: str | None
    account_id: str | None
    plan_id: str | None
    subscription_id: str | None
    carrier: dict = field(default_factory=dict)
