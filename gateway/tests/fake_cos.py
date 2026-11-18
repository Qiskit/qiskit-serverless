"""An in-memory COS for tests.

The gateway signs every COS request with the HMAC secret of a Code Engine project, so the fake keeps one set of files
per ``(project id, region)``. A storage only finds a file when it asks the same project, bucket and key it was
written to, as with the real COS. Only the lowest client is faked: the gateway's own ``get_cos_client_for`` and
``JobCOS`` run as in production.
"""

from collections import defaultdict
from unittest.mock import patch

from ibm_botocore.exceptions import ClientError

from core.ibm_cloud.code_engine.fleets.cos import JobCOS


class FakeCOS:
    """The files of every Code Engine project's COS, by ``(project id, region)`` and then ``(bucket, key)``."""

    def __init__(self):
        self._accounts: dict[tuple[str, str], dict[tuple[str, str], bytes]] = defaultdict(dict)

    def put(self, project_id: str, region: str, bucket: str, key: str, content: str) -> None:
        """Write a file the way a job's container would."""
        self._accounts[(project_id, region)][(bucket, key)] = content.encode("utf-8")

    def read(self, project_id: str, region: str, bucket: str, key: str) -> str | None:
        """The file's content, or None if it isn't there."""
        content = self._accounts[(project_id, region)].get((bucket, key))
        return content.decode("utf-8") if content is not None else None

    def installed(self):
        """Make the gateway's COS clients use these files instead of IBM Cloud."""
        return patch(
            "core.ibm_cloud._create_cos_client",
            lambda project_id, region: JobCOS(_FakeCOSClient(self._accounts[(project_id, region)])),
        )


class _FakeCOSClient:
    """The ``COSClient`` methods ``JobCOS`` calls, against one project's files."""

    def __init__(self, files: dict[tuple[str, str], bytes]):
        self._files = files

    def get_object_bytes(self, *, bucket: str, key: str) -> bytes:
        try:
            return self._files[(bucket, key)]
        except KeyError:
            raise ClientError({"Error": {"Code": "NoSuchKey", "Message": ""}}, "GetObject") from None

    def upload_fileobj(
        self, *, fileobj, bucket: str, key: str, callback=None
    ) -> None:  # pylint: disable=unused-argument
        self._files[(bucket, key)] = fileobj.read()

    def delete_object(self, *, bucket: str, key: str, **_wait) -> None:
        self._files.pop((bucket, key), None)

    def list_with_metadata(self, *, bucket: str, prefix: str) -> list[dict]:
        return [
            {"key": key, "size": len(content), "last_modified": None}
            for (in_bucket, key), content in sorted(self._files.items())
            if in_bucket == bucket and key.startswith(prefix)
        ]
