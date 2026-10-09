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
    FLEETS_BREAKER_FAILURES = "scheduler.fleets.breaker_failures"
    FLEETS_BREAKER_PAUSE_SECONDS = "scheduler.fleets.breaker_pause_seconds"
