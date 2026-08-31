"""Output dataclass for _get_runner_config."""

from dataclasses import dataclass

from core.models import ComputeProfile


@dataclass(frozen=True)
class RunnerConfig:
    """Resolved (compute_profile string, gpu flag, compute_profile FK) for a run."""

    compute_profile: str | None
    gpu: bool
    compute_profile_fk: ComputeProfile | None
