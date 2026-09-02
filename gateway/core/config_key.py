"""Dynamic configuration keys and defaults."""

from enum import Enum


class ConfigKey(Enum):
    """Dynamic configuration keys. Default values are configured in settings.DYNAMIC_CONFIG_DEFAULTS."""

    MAINTENANCE = "scheduler.maintenance"
    UPLOAD_FILE_VALID_MIME_TYPES = "gateway.upload_file.valid_mime_types"
    RUNTIME_INSTANCES_API_ENABLED = "gateway.runtime_instances_api.enabled"
    FILLER_ENABLED = "scheduler.filler.enabled"
    FILLER_PROGRAM_ID = "scheduler.filler.program_id"
    FILLER_SLOTS = "scheduler.filler.slots"
