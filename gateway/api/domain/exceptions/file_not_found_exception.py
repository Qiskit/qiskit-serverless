"""File not found exception."""

from typing import Optional
from api.domain.exceptions.not_found_exception import NotFoundError


class FileNotFoundException(NotFoundError):
    """Exception raised when a file is not found."""

    def __init__(self, file: Optional[str] = None):
        self.file = file
        message = "Requested file was not found."
        if file:
            message = f"File {file} was not found."
        super().__init__(message)
