"""The scenarios.yaml and metrics.yaml models. Unknown keys are rejected."""

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class Strict(BaseModel):
    """A model that refuses unknown keys."""

    model_config = ConfigDict(extra="forbid")


class Limits(Strict):
    """The most a run may create, checked before it starts."""

    max_jobs: int = 600
    max_users: int = 250


class Sysdig(Strict):
    """The IBM Cloud Monitoring instance that sees the cluster under test."""

    region: str
    instance_id: str
    cluster: str
    metrics: str = "metrics.yaml"


class CodeEngine(Strict):
    """The Code Engine project the jobs run in, so cleanup can delete their fleets and a run can wait for room."""

    project_id: str
    region: str


class CloudLogs(Strict):
    """The IBM Cloud Logs instance with the gateway and scheduler logs, for the time of each submit."""

    region: str
    instance_id: str


class Defaults(Strict):
    """Settings shared by every scenario."""

    gateway: str
    poll_seconds: float = 5
    limits: Limits = Limits()
    sysdig: Sysdig | None = None
    code_engine: CodeEngine | None = None
    cloud_logs: CloudLogs | None = None
    # the wait after a scenario, so the next one starts with an idle scheduler and its fleets deleted
    cooldown_seconds: float = Field(default=300, ge=0)

    @field_validator("sysdig", "code_engine", "cloud_logs", mode="before")
    @classmethod
    def _off_when_empty(cls, value):
        """A section whose ids come from unset env vars is off, so the run works without that service."""
        if isinstance(value, dict) and not all(v for k, v in value.items() if k != "metrics"):
            return None
        return value


class Function(Strict):
    """A function folder in functions/. Each user uploads it as <title>-u<n>, with these sizes."""

    path: str
    entrypoint: str
    title: str
    sizes: dict[str, str]
    default_size: str


class Scenario(Strict):
    """One scenario. Users submit through a rate limiter: `burst` of them at once, then `qps` per second."""

    name: str
    users: int = Field(gt=0)
    qps: float = Field(gt=0)
    burst: int = Field(gt=0)
    function_size: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)

    def submit_seconds(self) -> float:
        """How long it takes until the last user submits."""
        return max(0, self.users - self.burst) / self.qps


class Config(Strict):
    """The whole scenarios.yaml."""

    defaults: Defaults
    function: Function
    sqd_arguments: dict[str, Any] = Field(default_factory=dict)  # shared by the scenarios through a YAML anchor
    scenarios: list[Scenario]

    @model_validator(mode="after")
    def _check_sizes(self):
        for scenario in self.scenarios:
            size = scenario.function_size or self.function.default_size
            if size not in self.function.sizes:
                raise ValueError(f"{scenario.name}: size {size} is not one of {sorted(self.function.sizes)}")
        return self


class Metric(Strict):
    """One PromQL query. `read: last` reads a running total at the end of the window, `max` the peak."""

    name: str
    query: str
    read: Literal["max", "last"] = "max"


class Metrics(Strict):
    """The whole metrics.yaml."""

    namespace: str
    step_seconds: int = 15
    metrics: list[Metric]


def _expand_env(text: str) -> str:
    """Replace ${NAME} with the env var, and fail when it is not set. ${NAME:-} is empty when it is not set."""

    def value(match: re.Match) -> str:
        name, optional = match.group(1), match.group(2)
        if name not in os.environ and optional is None:
            raise SystemExit(f"Set {name}, the scenarios file uses it.")
        return os.environ.get(name, "")

    return re.sub(r"\$\{(\w+)(:-)?\}", value, text)


def _load(model, path: Path, text: str):
    try:
        return model.model_validate(yaml.safe_load(text))
    except ValidationError as exc:
        raise SystemExit(f"{path} is not valid:\n{exc}") from exc


def load_config(path: Path) -> Config:
    """Read scenarios.yaml."""
    return _load(Config, path, _expand_env(path.read_text()))


def load_metrics(path: Path) -> Metrics:
    """Read metrics.yaml."""
    return _load(Metrics, path, path.read_text())
