from dataclasses import dataclass


@dataclass
class JobEvent:  # pylint: disable=too-many-instance-attributes
    """Job Event data.

    Args:
        workers: number of worker pod when auto scaling is NOT enabled
        auto_scaling: set True to enable auto scaling of the workers
        min_workers: minimum number of workers when auto scaling is enabled
        max_workers: maximum number of workers when auto scaling is enabled
    """

    event_type: str
    origin: str
    context: str
    created: str
    data: dict
