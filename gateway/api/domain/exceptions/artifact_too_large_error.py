"""The error of a function upload over the size limit."""


class ArtifactTooLargeError(Exception):
    """The files of a function upload are over the size limit."""

    def __init__(self, size_bytes: int, limit_mb: int):
        self.message = f"the function files are {size_bytes / 1024**2:.1f} MB, more than the {limit_mb} MB allowed"
        super().__init__(self.message)
