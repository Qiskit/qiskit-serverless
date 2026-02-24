"""Dynamic configuration keys and defaults."""

from enum import Enum


class ConfigKey(Enum):
    """Dynamic configuration keys. Default values are configured in settings.DYNAMIC_CONFIG_DEFAULTS."""

    MAINTENANCE = "scheduler.maintenance"

    LIMITS_JOBS_PER_USER = "scheduler.limits.jobs_per_user"

    LIMITS_CPU_CLUSTERS = "scheduler.limits.cpu_clusters"
    LIMITS_GPU_CLUSTERS = "scheduler.limits.gpu_clusters"
    LIMITS_CPU_PER_TASK = "scheduler.limits.cpu_per_task"
    LIMITS_GPU_PER_TASK = "scheduler.limits.gpu_per_task"

    LIMITS_MEMORY_PER_TASK = "scheduler.limits.memory_per_task"
