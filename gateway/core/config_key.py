"""Dynamic configuration keys and defaults."""

from enum import Enum


class ConfigKey(Enum):
    """Dynamic configuration keys. Default values are configured in settings.DYNAMIC_CONFIG_DEFAULTS."""

    MAINTENANCE = "scheduler.maintenance"
    UPLOAD_FILE_VALID_MIME_TYPES = "upload_file.valid_mime_types"
