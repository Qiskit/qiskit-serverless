"""
This module handle the access to the files store
"""

from abc import ABC, abstractmethod
import logging
from typing import Iterator, Optional, Tuple
from wsgiref.util import FileWrapper

from django.core.files import File

logger = logging.getLogger("core.FileStorage")


class FileStorage(ABC):
    """
    The main objective of this class is to manage the access of the users to their storage.
    """

    @abstractmethod
    def get_public_files(self) -> list[str]:
        """
        This method returns a list of file names following the next rules:
            - It returns only files from a user or a provider file storage
            - Directories are excluded

        Returns:
            list[str]: list of file names
        """

    @abstractmethod
    def get_private_files(self) -> list[str]:
        """
        This method returns a list of file names following the next rules:
            - It returns only files from a user or a provider file storage
            - Directories are excluded

        Returns:
            list[str]: list of file names
        """

    @abstractmethod
    def get_public_file(self, file_name: str) -> Optional[Tuple[FileWrapper, str, int]]:
        """
        This method returns a file from file_name:
            - Only files with supported extensions are available to download
            - It returns only a file from a user or a provider file storage
            - FileWrapper is iterable only from the file system. From mounted COS volumes, use get_file_stream instead

        Args:
            file_name (str): the name of the file to download

        Returns:
            FileWrapper: the file itself
            str: with the type of the file
            int: with the size of the file
        """

    @abstractmethod
    def get_private_file(self, file_name: str) -> Optional[Tuple[FileWrapper, str, int]]:
        """
        This method returns a file from file_name:
            - Only files with supported extensions are available to download
            - It returns only a file from a user or a provider file storage
            - FileWrapper is iterable only from the file system. From mounted COS volumes, use get_file_stream instead

        Args:
            file_name (str): the name of the file to download

        Returns:
            FileWrapper: the file itself
            str: with the type of the file
            int: with the size of the file
        """

    @abstractmethod
    def get_public_file_stream(
        self, file_name: str, chunk_size: int = 65536
    ) -> Optional[Tuple[Iterator[bytes], str, int]]:
        """
        This method returns a streaming generator for a file that we can use for large files

        Args:
            file_name (str): the name of the file to download
            chunk_size (int): bytes per chunk (default 64 KB)

        Returns:
            Iterator[bytes]: generator that yields file chunks
            str: with the type of the file
            int: with the size of the file
        """

    @abstractmethod
    def get_private_file_stream(
        self, file_name: str, chunk_size: int = 65536
    ) -> Optional[Tuple[Iterator[bytes], str, int]]:
        """
        This method returns a streaming generator for a file that we can use for large files

        Args:
            file_name (str): the name of the file to download
            chunk_size (int): bytes per chunk (default 64 KB)

        Returns:
            Iterator[bytes]: generator that yields file chunks
            str: with the type of the file
            int: with the size of the file
        """

    @abstractmethod
    def upload_public_file(self, file: File) -> str:
        """
        This method uploads a file to the specific path:
            - Only files with supported extensions are available to download
            - It returns only a file from a user or a provider file storage

        Args:
            file (django.File): the file to store in the specific path

        Returns:
            str: the path where the file was stored
        """

    @abstractmethod
    def upload_private_file(self, file: File) -> str:
        """
        This method uploads a file to the specific path:
            - Only files with supported extensions are available to download
            - It returns only a file from a user or a provider file storage

        Args:
            file (django.File): the file to store in the specific path

        Returns:
            str: the path where the file was stored
        """

    @abstractmethod
    def remove_public_file(self, file_name: str) -> bool:
        """
        This method removes a file in the path of file_name

        Args:
            file_name (str): the name of the file to remove

        Returns:
            - True if it was deleted
            - False otherwise
        """

    @abstractmethod
    def remove_private_file(self, file_name: str) -> bool:
        """
        This method removes a file in the path of file_name

        Args:
            file_name (str): the name of the file to remove

        Returns:
            - True if it was deleted
            - False otherwise
        """
