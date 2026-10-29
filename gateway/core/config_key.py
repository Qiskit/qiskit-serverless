"""Dynamic configuration keys and defaults."""

from enum import Enum


class ConfigKey(Enum):
    """Dynamic configuration keys. Default values are configured in settings.DYNAMIC_CONFIG_DEFAULTS."""

    MAINTENANCE = "scheduler.maintenance"
    UPLOAD_FILE_VALID_MIME_TYPES = "gateway.upload_file.valid_mime_types"
    RUNTIME_INSTANCES_API_ENABLED = "gateway.runtime_instances_api.enabled"
    FILLER_ENABLED = "scheduler.filler.enabled"
    FILLER_FUNCTION = "scheduler.filler.function"
    FILLER_SLOTS = "scheduler.filler.slots"
    OUTBOX_KAFKA_CHANNEL_BUDGET_MS = "scheduler.outbox.kafka.budget_ms"
    OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES = "scheduler.outbox.kafka.breaker_failures"
    OUTBOX_KAFKA_CHANNEL_BREAKER_PAUSE_SECONDS = "scheduler.outbox.kafka.breaker_pause_seconds"
    OUTBOX_KAFKA_CHANNEL_RETRY_BASE_SECONDS = "scheduler.outbox.kafka.retry_base_seconds"
    OUTBOX_KAFKA_CHANNEL_RETRY_MAX_SECONDS = "scheduler.outbox.kafka.retry_max_seconds"
    WORKLOADS_MIRROR_ENABLED = "workloads.mirror.enabled"
    OUTBOX_WORKLOAD_CHANNEL_BUDGET_MS = "scheduler.outbox.workload.budget_ms"
    OUTBOX_WORKLOAD_CHANNEL_BREAKER_FAILURES = "scheduler.outbox.workload.breaker_failures"
    OUTBOX_WORKLOAD_CHANNEL_BREAKER_PAUSE_SECONDS = "scheduler.outbox.workload.breaker_pause_seconds"
    OUTBOX_WORKLOAD_CHANNEL_RETRY_BASE_SECONDS = "scheduler.outbox.workload.retry_base_seconds"
    OUTBOX_WORKLOAD_CHANNEL_RETRY_MAX_SECONDS = "scheduler.outbox.workload.retry_max_seconds"

    FLEETS_CLEANUP_ENABLED = "scheduler.fleets.cleanup.enabled"
    FLEETS_CLEANUP_RETENTION_HOURS = "scheduler.fleets.cleanup.retention_hours"
    FLEETS_CLEANUP_FORCE_AT_PERCENT = "scheduler.fleets.cleanup.force_at_percent"
    FLEETS_CLEANUP_BUDGET_MS = "scheduler.fleets.cleanup.budget_ms"
    FLEETS_CLEANUP_MAX_DELETES = "scheduler.fleets.cleanup.max_deletes_per_cycle"
    FLEETS_QUOTA_PER_PROJECT = "scheduler.fleets.quota_per_project"
    FLEETS_BREAKER_FAILURES = "scheduler.fleets.breaker_failures"
    FLEETS_BREAKER_PAUSE_SECONDS = "scheduler.fleets.breaker_pause_seconds"
    BLOCKED_RESOURCES_ENFORCED = "scheduler.blocked_resources.enforced"
