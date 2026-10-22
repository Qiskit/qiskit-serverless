"""Output dataclass for _get_runner_config."""

from dataclasses import dataclass

from core.models import ComputeProfile, FunctionSize


@dataclass(frozen=True)
class RunnerConfig:
    """Resolved sizing for a run.

    Carries the compute profile FK the job runs at plus provenance:
    ``size_source`` records how sizing was chosen and ``function_size`` is the
    size row it resolved to, when one applies. These let a stored job be told
    apart even when different sizes map to the same compute profile.
    """

    gpu: bool
    compute_profile_fk: ComputeProfile | None
    size_source: str
    function_size: FunctionSize | None
