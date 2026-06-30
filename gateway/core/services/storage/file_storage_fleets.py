"""
This module handle the access to the files store
"""

from dataclasses import dataclass
from io import BytesIO
import logging
import os
from typing import Iterator, Optional, Tuple
from wsgiref.util import FileWrapper

from ibm_botocore.exceptions import ClientError
from django.core.files import File

from core.ibm_cloud import get_cos_client
from core.models import Program

logger = logging.getLogger("core.FileStorage")

# BytesIO is used for streaming file chunks from COS bytes


@dataclass(frozen=True)
class FleetFunctionPaths:  # pylint: disable=too-many-instance-attributes
    """Computed paths for a fleet function.

    ``cos_*`` fields are bucket-relative paths used by the Gateway to read/write COS objects.

    Fields ending in ``_prefix`` are directory-scoped (no trailing slash, no filename) and serve two purposes:
       - As the ``sub_path`` argument of a PDS volume mount
       - As the base for building COS keys for files whose names are only known at runtime

    Fields ending in ``_key`` are complete object keys, usable directly with the S3 client.

    ``container_*`` fields are absolute paths inside the running container.

    Mount layout (4 PDS volumes):
      FUNCTION_USER_DATA_PATH   → user bucket   @ cos_user_function_prefix   (function-scoped user data)
      JOB_USER_DATA_PATH        → user bucket   @ cos_user_job_prefix        (job-scoped user data)
      FUNCTION_PROVIDER_DATA_PATH → provider bucket @ cos_provider_function_prefix  (provider only)
      JOB_PROVIDER_DATA_PATH    → provider bucket @ cos_provider_job_prefix   (provider only)
    """

    # COS prefixes — used as PDS volume mount sub_paths and as key bases
    cos_user_files_prefix: str  # # providers/.../data/  — FUNCTION_USER_DATA_PATH sub_path (None for custom)
    cos_provider_files_prefix: str  # providers/.../data/  — FUNCTION_PROVIDER_DATA_PATH sub_path (None for custom)


class FileStorageFleets:
    """
    The main objective of this class is to manage the access of the users to their storage.
    """

    NOT_FOUND_CODES = ["NoSuchKey", "NotFound"]

    def __init__(
        self,
        username: str,
        function: Program,
    ) -> None:
        """
        Initialize FileStorage with a function instance.

        Args:
            username: User's username
            function: Program model instance containing title and provider
        """
        paths = self._build_function_paths(function, username)
        self._function_id = str(function.id)
        self._user_id = username
        self._project = function.code_engine_project
        self._public_folder_key = paths.cos_user_files_prefix
        self._private_folder_key: Optional[str] = paths.cos_provider_files_prefix
        self._user_bucket = self._load_user_bucket(function)
        self._provider_bucket = self._load_provider_bucket(function)

    def get_public_files(self) -> list[str]:
        """
        This method returns a list of file names following the next rules:
            - It returns only files from a user or a provider file storage
            - Directories are excluded

        Returns:
            list[str]: list of file names
        """
        try:
            files = get_cos_client(self._project).list_keys(
                bucket_name=self._user_bucket, prefix=self._public_folder_key
            )
            logger.info(
                "[get-public-files] user_id=%s function_id=%s bucket=%s key=%s Files retrieved from COS",
                self._user_id,
                self._function_id,
                self._user_bucket,
                self._public_folder_key,
            )
            return [os.path.basename(f) for f in files]
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in self.NOT_FOUND_CODES:
                logger.warning(
                    "[get-public-files] user_id=%s function_id=%s | Files not found in COS at %s/%s",
                    self._user_id,
                    self._function_id,
                    self._user_bucket,
                    self._public_folder_key,
                )
                return []
            logger.error(
                "[get-public-files] user_id=%s function_id=%s | COS error %s: %s",
                self._user_id,
                self._function_id,
                code,
                e,
            )
            return []

    def get_private_files(self) -> Optional[list[str]]:
        """
        This method returns a list of file names following the next rules:
            - It returns only files from a user or a provider file storage
            - Directories are excluded

        Returns:
            list[str]: list of file names
        """
        if not self._private_folder_key:
            return None

        try:
            files = get_cos_client(self._project).list_keys(
                bucket_name=self._provider_bucket, prefix=self._private_folder_key
            )
            logger.info(
                "[get-private-files] user_id=%s function_id=%s bucket=%s key=%s Files retrieved from COS",
                self._user_id,
                self._function_id,
                self._provider_bucket,
                self._private_folder_key,
            )
            return [os.path.basename(f) for f in files]
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in self.NOT_FOUND_CODES:
                logger.warning(
                    "[get-private-files] user_id=%s function_id=%s | Files not found in COS at %s/%s",
                    self._user_id,
                    self._function_id,
                    self._provider_bucket,
                    self._private_folder_key,
                )
                return None
            logger.error(
                "[get-private-files] user_id=%s function_id=%s | COS error %s: %s",
                self._user_id,
                self._function_id,
                code,
                e,
            )
            return None

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
        key = f"{self._public_folder_key}/{file_name}"
        try:
            content_bytes = get_cos_client(self._project).get_object_bytes(bucket_name=self._user_bucket, key=key)
            logger.info(
                "[get-public-file] user_id=%s function_id=%s bucket=%s key=%s File retrieved from COS",
                self._user_id,
                self._function_id,
                self._user_bucket,
                key,
            )
            return (FileWrapper(content_bytes), "application/octet-stream", len(content_bytes))
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in self.NOT_FOUND_CODES:
                logger.warning(
                    "[get-public-file] user_id=%s function_id=%s | File not found in COS at %s/%s",
                    self._user_id,
                    self._function_id,
                    self._user_bucket,
                    key,
                )
                return None
            logger.error(
                "[get-public-file] user_id=%s function_id=%s | COS error %s: %s",
                self._user_id,
                self._function_id,
                code,
                e,
            )
            return None

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
        if not self._private_folder_key:
            return None

        key = f"{self._private_folder_key}/{file_name}"
        try:
            content_bytes = get_cos_client(self._project).get_object_bytes(bucket_name=self._provider_bucket, key=key)
            logger.info(
                "[get-private-file] user_id=%s function_id=%s bucket=%s key=%s File retrieved from COS",
                self._user_id,
                self._function_id,
                self._provider_bucket,
                key,
            )
            return (FileWrapper(content_bytes), "application/octet-stream", len(content_bytes))
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in self.NOT_FOUND_CODES:
                logger.warning(
                    "[get-private-file] user_id=%s function_id=%s | File not found in COS at %s/%s",
                    self._user_id,
                    self._function_id,
                    self._provider_bucket,
                    key,
                )
                return None
            logger.error(
                "[get-private-file] user_id=%s function_id=%s | COS error %s: %s",
                self._user_id,
                self._function_id,
                code,
                e,
            )
            return None

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
        key = f"{self._public_folder_key}/{file_name}"
        try:
            content_bytes = get_cos_client(self._project).get_object_bytes(bucket_name=self._user_bucket, key=key)
            file_size = len(content_bytes)
            file_obj = BytesIO(content_bytes)

            def stream_generator():
                while True:
                    chunk = file_obj.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk

            logger.info(
                "[get-public-file-stream] user_id=%s function_id=%s bucket=%s key=%s Stream initiated",
                self._user_id,
                self._function_id,
                self._user_bucket,
                key,
            )
            return (stream_generator(), "application/octet-stream", file_size)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in self.NOT_FOUND_CODES:
                logger.warning(
                    "[get-public-file-stream] user_id=%s function_id=%s | File not found in COS at %s/%s",
                    self._user_id,
                    self._function_id,
                    self._user_bucket,
                    key,
                )
                return None
            logger.error(
                "[get-public-file-stream] user_id=%s function_id=%s | COS error %s: %s",
                self._user_id,
                self._function_id,
                code,
                e,
            )
            return None

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
        if not self._private_folder_key:
            return None

        key = f"{self._private_folder_key}/{file_name}"
        try:
            content_bytes = get_cos_client(self._project).get_object_bytes(bucket_name=self._provider_bucket, key=key)
            file_size = len(content_bytes)
            file_obj = BytesIO(content_bytes)

            def stream_generator():
                while True:
                    chunk = file_obj.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk

            logger.info(
                "[get-private-file-stream] user_id=%s function_id=%s bucket=%s key=%s Stream initiated",
                self._user_id,
                self._function_id,
                self._provider_bucket,
                key,
            )
            return (stream_generator(), "application/octet-stream", file_size)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in self.NOT_FOUND_CODES:
                logger.warning(
                    "[get-private-file-stream] user_id=%s function_id=%s | File not found in COS at %s/%s",
                    self._user_id,
                    self._function_id,
                    self._provider_bucket,
                    key,
                )
                return None
            logger.error(
                "[get-private-file-stream] user_id=%s function_id=%s | COS error %s: %s",
                self._user_id,
                self._function_id,
                code,
                e,
            )
            return None

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
        key = f"{self._public_folder_key}/{file.name}"
        try:
            get_cos_client(self._project).upload_fileobj(fileobj=file, bucket_name=self._user_bucket, key=key)
            logger.info(
                "[upload-public-file] user_id=%s function_id=%s bucket=%s key=%s File uploaded",
                self._user_id,
                self._function_id,
                self._user_bucket,
                key,
            )
            return file.name
        except ClientError as e:
            logger.error(
                "[upload-public-file] user_id=%s function_id=%s | COS error %s: %s",
                self._user_id,
                self._function_id,
                e.response.get("Error", {}).get("Code", ""),
                e,
            )
            raise

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
        if not self._private_folder_key:
            raise ValueError("Private folder key is not configured")

        key = f"{self._private_folder_key}/{file.name}"
        try:
            get_cos_client(self._project).upload_fileobj(fileobj=file, bucket_name=self._provider_bucket, key=key)
            logger.info(
                "[upload-private-file] user_id=%s function_id=%s bucket=%s key=%s File uploaded",
                self._user_id,
                self._function_id,
                self._provider_bucket,
                key,
            )
            return file.name
        except ClientError as e:
            logger.error(
                "[upload-private-file] user_id=%s function_id=%s | COS error %s: %s",
                self._user_id,
                self._function_id,
                e.response.get("Error", {}).get("Code", ""),
                e,
            )
            raise

    def remove_public_file(self, file_name: str) -> bool:
        """
        This method removes a file in the path of file_name

        Args:
            file_name (str): the name of the file to remove

        Returns:
            - True if it was deleted
            - False otherwise
        """
        key = f"{self._public_folder_key}/{file_name}"
        try:
            get_cos_client(self._project).delete_object(bucket_name=self._user_bucket, key=key)
            logger.info(
                "[remove-public-file] user_id=%s function_id=%s bucket=%s key=%s File removed",
                self._user_id,
                self._function_id,
                self._user_bucket,
                key,
            )
            return True
        except ClientError as e:
            logger.error(
                "[remove-public-file] user_id=%s function_id=%s | COS error %s: %s",
                self._user_id,
                self._function_id,
                e.response.get("Error", {}).get("Code", ""),
                e,
            )
            return False

    def remove_private_file(self, file_name: str) -> bool:
        """
        This method removes a file in the path of file_name

        Args:
            file_name (str): the name of the file to remove

        Returns:
            - True if it was deleted
            - False otherwise
        """
        if not self._private_folder_key:
            return False

        key = f"{self._private_folder_key}/{file_name}"
        try:
            get_cos_client(self._project).delete_object(bucket_name=self._provider_bucket, key=key)
            logger.info(
                "[remove-private-file] user_id=%s function_id=%s bucket=%s key=%s File removed",
                self._user_id,
                self._function_id,
                self._provider_bucket,
                key,
            )
            return True
        except ClientError as e:
            logger.error(
                "[remove-private-file] user_id=%s function_id=%s | COS error %s: %s",
                self._user_id,
                self._function_id,
                e.response.get("Error", {}).get("Code", ""),
                e,
            )
            return False

    def _load_user_bucket(self, function: Program) -> str:
        """Load the user bucket for the function."""
        if not function.code_engine_project:
            raise ValueError(f"Program '{function.id}' has no CodeEngineProject assigned")

        user_bucket = function.code_engine_project.cos_bucket_user_data_name
        if not user_bucket:
            project_name = function.code_engine_project.project_name
            raise ValueError(f"CodeEngineProject '{project_name}' has no " "cos_bucket_user_data_name configured")
        return user_bucket

    def _load_provider_bucket(self, function: Program) -> Optional[str]:
        """Load the provider bucket for the function."""
        if not function.code_engine_project:
            raise ValueError(f"Program '{function.id}' has no CodeEngineProject assigned")

        if not function.provider:
            return None

        provider_bucket = function.code_engine_project.cos_bucket_provider_data_name
        if not provider_bucket:
            project_name = function.code_engine_project.project_name
            raise ValueError(f"CodeEngineProject '{project_name}' has no " "cos_bucket_provider_data_name configured")
        return provider_bucket

    def _build_custom_function_paths(self, function: Program, username: str) -> FleetFunctionPaths:
        """COS paths for a custom (non-provider) job.

        The entrypoint and wrapper live in the user bucket at function scope
        (``FUNCTION_USER_DATA_PATH``). Arguments, logs, and results live in the
        user bucket at job scope (``JOB_USER_DATA_PATH``). There are no private logs
        and no provider bucket mounts.

        Field naming conventions:
        - ``cos_*``       — bucket-relative COS object keys or key prefixes,
                            used by the gateway to read/write objects via the S3 client.
        - ``container_*`` — absolute paths inside the running container,
                            injected as env vars (ARGUMENTS_PATH, RESULTS_PATH, etc.)
                            or passed directly to the wrapper/entrypoint command.
        - ``*_prefix``    — directory-scoped key (no trailing slash); doubles as the
                            ``sub_path`` for the PDS volume mount and as the base for
                            building object keys at runtime.
        - ``*_key``       — complete object key, usable directly with the S3 client.
        - ``*_entrypoint``— key or path to the script that CE runs as the job entry.
        - ``*_docker_entrypoint`` — key or path to the fleet wrapper script that
                                    handles log capture and invokes the entrypoint.

        Args:
            function: Job instance with no provider.
        """

        program_title = function.title
        cos_user_function_data = f"users/{username}/custom_functions/{program_title}/data"
        return FleetFunctionPaths(
            cos_user_files_prefix=cos_user_function_data,
            cos_provider_files_prefix=None,
        )

    def _build_provider_function_paths(self, function: Program, username: str) -> FleetFunctionPaths:
        """COS paths for a provider job.

        The entrypoint and wrapper live in the provider bucket at function scope
        (``FUNCTION_PROVIDER_DATA_PATH``). User-facing data lives in the user bucket
        at both function scope (``FUNCTION_USER_DATA_PATH``) and job scope
        (``JOB_USER_DATA_PATH``). Private provider logs live in the provider bucket
        at job scope (``JOB_PROVIDER_DATA_PATH``).

        See :func:`build_custom_job_paths` for field naming conventions.

        Args:
            job: Job instance with a provider assigned.
        """

        provider_name = function.provider.name
        program_title = function.title
        cos_user_function_data = f"users/{username}/provider_functions/{provider_name}/{program_title}/data"
        cos_provider_function_data = f"providers/{provider_name}/{program_title}/data"
        return FleetFunctionPaths(
            cos_user_files_prefix=cos_user_function_data,
            cos_provider_files_prefix=cos_provider_function_data,
        )

    def _build_function_paths(self, function: Program, username: str) -> FleetFunctionPaths:
        if function.provider:
            return self._build_provider_function_paths(function, username)
        return self._build_custom_function_paths(function, username)
