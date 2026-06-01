# Fleet Logs Presigned URL Redirect — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace in-memory COS log downloads for Fleet jobs with HTTP 302 redirects to presigned COS URLs, removing the gateway from the data path.

**Architecture:** For Fleet jobs only, the gateway generates a time-limited presigned URL via `ibm_boto3` and returns `302 Location: <url>`; the client follows the redirect transparently and receives raw log text directly from COS. When no log object exists yet, the endpoint returns `204 No Content`. Ray job behavior is unchanged (200 JSON). A new `LogsResult` dataclass carries the discriminated return value from use cases to views.

**Tech Stack:** Python, Django REST Framework, `ibm_boto3` (S3-compatible presigned URLs), `requests` (client), pytest

---

## File Map

| Action | Path |
|--------|------|
| Modify | `gateway/core/ibm_cloud/cos/cos_client.py` |
| Modify | `gateway/core/ibm_cloud/code_engine/fleets/cos.py` |
| Modify | `gateway/core/services/storage/logs_storage.py` |
| Modify | `gateway/core/services/storage/logs_storage_ray.py` |
| Modify | `gateway/core/services/storage/logs_storage_fleets.py` |
| **Create** | `gateway/api/use_cases/jobs/logs_result.py` |
| Modify | `gateway/api/use_cases/jobs/get_logs.py` |
| Modify | `gateway/api/use_cases/jobs/provider_logs.py` |
| Modify | `gateway/api/v1/views/jobs/get_logs.py` |
| Modify | `gateway/api/v1/views/jobs/provider_logs.py` |
| Modify | `client/qiskit_serverless/core/clients/serverless_client.py` |
| Modify (tests) | `gateway/tests/core/services/ibm_cloud/cos/test_cos_client_unit.py` |
| Modify (tests) | `gateway/tests/core/services/ibm_cloud/code_engine/fleets/test_job_cos_unit.py` |
| Modify (tests) | `gateway/tests/core/services/storage/test_logs_storage.py` |
| Modify (tests) | `gateway/tests/core/services/storage/test_logs_storage_fleets.py` |
| Modify (tests) | `gateway/tests/api/use_cases/jobs/test_logs_use_cases_fleets.py` |
| Modify (tests) | `gateway/tests/api/test_logs.py` |
| Modify (tests) | `client/tests/core/test_serverless_client_jobs.py` |

---

## Task 1: `COSClient` — `head_object` and `generate_presigned_url`

**Files:**
- Modify: `gateway/core/ibm_cloud/cos/cos_client.py`
- Test: `gateway/tests/core/services/ibm_cloud/cos/test_cos_client_unit.py`

- [ ] **Step 1: Write failing tests**

Append to `gateway/tests/core/services/ibm_cloud/cos/test_cos_client_unit.py`:

```python
def test_head_object_calls_s3_head_object() -> None:
    """head_object() delegates to the underlying S3 head_object."""
    client, mock_s3 = _make_client()
    client.head_object(bucket="my-bucket", key="some/key")
    mock_s3.head_object.assert_called_once_with(Bucket="my-bucket", Key="some/key")


def test_generate_presigned_url_calls_s3_generate_presigned_url() -> None:
    """generate_presigned_url() delegates to the underlying S3 client."""
    client, mock_s3 = _make_client()
    mock_s3.generate_presigned_url.return_value = "https://cos.example.com/key?sig=abc"

    url = client.generate_presigned_url(bucket="my-bucket", key="some/key", expiry=1800)

    mock_s3.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={"Bucket": "my-bucket", "Key": "some/key"},
        ExpiresIn=1800,
    )
    assert url == "https://cos.example.com/key?sig=abc"


def test_generate_presigned_url_default_expiry() -> None:
    """generate_presigned_url() uses 3600s expiry by default."""
    client, mock_s3 = _make_client()
    mock_s3.generate_presigned_url.return_value = "https://cos.example.com/key?sig=abc"

    client.generate_presigned_url(bucket="my-bucket", key="some/key")

    _, kwargs = mock_s3.generate_presigned_url.call_args
    assert kwargs["ExpiresIn"] == 3600
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd gateway && python -m pytest tests/core/services/ibm_cloud/cos/test_cos_client_unit.py::test_head_object_calls_s3_head_object tests/core/services/ibm_cloud/cos/test_cos_client_unit.py::test_generate_presigned_url_calls_s3_generate_presigned_url tests/core/services/ibm_cloud/cos/test_cos_client_unit.py::test_generate_presigned_url_default_expiry -v
```

Expected: FAIL with `AttributeError` or similar (methods don't exist yet).

- [ ] **Step 3: Implement in `COSClient`**

Append these two methods at the end of the `COSClient` class in `gateway/core/ibm_cloud/cos/cos_client.py` (after `get_object_bytes`, before the final line of the file):

```python
    def head_object(self, *, bucket: str, key: str) -> None:
        """Check that an object exists.

        Raises:
            ClientError: If the object does not exist or an error occurs.
        """
        self._s3_hmac.head_object(Bucket=bucket, Key=key)

    def generate_presigned_url(self, *, bucket: str, key: str, expiry: int = 3600) -> str:
        """Generate a presigned GET URL for an object.

        Args:
            bucket: Bucket name.
            key: Object key.
            expiry: URL validity in seconds (default 3600).

        Returns:
            Presigned URL string.
        """
        return self._s3_hmac.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expiry,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd gateway && python -m pytest tests/core/services/ibm_cloud/cos/test_cos_client_unit.py::test_head_object_calls_s3_head_object tests/core/services/ibm_cloud/cos/test_cos_client_unit.py::test_generate_presigned_url_calls_s3_generate_presigned_url tests/core/services/ibm_cloud/cos/test_cos_client_unit.py::test_generate_presigned_url_default_expiry -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gateway/core/ibm_cloud/cos/cos_client.py gateway/tests/core/services/ibm_cloud/cos/test_cos_client_unit.py
git commit -m "Add head_object and generate_presigned_url to COSClient"
```

---

## Task 2: `JobCOS` — `head_object` and `get_presigned_url`

**Files:**
- Modify: `gateway/core/ibm_cloud/code_engine/fleets/cos.py`
- Test: `gateway/tests/core/services/ibm_cloud/code_engine/fleets/test_job_cos_unit.py`

- [ ] **Step 1: Write failing tests**

Append to `gateway/tests/core/services/ibm_cloud/code_engine/fleets/test_job_cos_unit.py`:

```python
def test_job_cos_head_object() -> None:
    """head_object() delegates to COSClient.head_object."""
    job_cos, mock_cos = _make_job_cos()
    job_cos.head_object(bucket_name="my-bucket", key="some/key")
    mock_cos.head_object.assert_called_once_with(bucket="my-bucket", key="some/key")


def test_job_cos_head_object_raises_on_empty_bucket() -> None:
    """head_object() raises ValueError when bucket_name is empty."""
    job_cos, _ = _make_job_cos()
    with pytest.raises(ValueError, match="bucket_name"):
        job_cos.head_object(bucket_name="", key="some/key")


def test_job_cos_head_object_raises_on_empty_key() -> None:
    """head_object() raises ValueError when key is empty."""
    job_cos, _ = _make_job_cos()
    with pytest.raises(ValueError, match="key"):
        job_cos.head_object(bucket_name="my-bucket", key="")


def test_job_cos_get_presigned_url() -> None:
    """get_presigned_url() delegates to COSClient.generate_presigned_url."""
    job_cos, mock_cos = _make_job_cos()
    mock_cos.generate_presigned_url.return_value = "https://cos.example.com/key?sig=abc"

    url = job_cos.get_presigned_url(bucket_name="my-bucket", key="some/key", expiry=1800)

    mock_cos.generate_presigned_url.assert_called_once_with(
        bucket="my-bucket", key="some/key", expiry=1800
    )
    assert url == "https://cos.example.com/key?sig=abc"


def test_job_cos_get_presigned_url_default_expiry() -> None:
    """get_presigned_url() passes default expiry of 3600 to COSClient."""
    job_cos, mock_cos = _make_job_cos()
    mock_cos.generate_presigned_url.return_value = "https://cos.example.com/key?sig=abc"

    job_cos.get_presigned_url(bucket_name="my-bucket", key="some/key")

    _, kwargs = mock_cos.generate_presigned_url.call_args
    assert kwargs["expiry"] == 3600


def test_job_cos_get_presigned_url_raises_on_empty_bucket() -> None:
    """get_presigned_url() raises ValueError when bucket_name is empty."""
    job_cos, _ = _make_job_cos()
    with pytest.raises(ValueError, match="bucket_name"):
        job_cos.get_presigned_url(bucket_name="", key="some/key")


def test_job_cos_get_presigned_url_raises_on_empty_key() -> None:
    """get_presigned_url() raises ValueError when key is empty."""
    job_cos, _ = _make_job_cos()
    with pytest.raises(ValueError, match="key"):
        job_cos.get_presigned_url(bucket_name="my-bucket", key="")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd gateway && python -m pytest tests/core/services/ibm_cloud/code_engine/fleets/test_job_cos_unit.py::test_job_cos_head_object tests/core/services/ibm_cloud/code_engine/fleets/test_job_cos_unit.py::test_job_cos_get_presigned_url -v
```

Expected: FAIL.

- [ ] **Step 3: Implement in `JobCOS`**

Append these two methods at the end of the `JobCOS` class in `gateway/core/ibm_cloud/code_engine/fleets/cos.py` (after `list_keys`):

```python
    def head_object(self, *, bucket_name: str, key: str) -> None:
        """Check that an object exists in COS.

        Args:
            bucket_name: COS bucket name.
            key: Object key.

        Raises:
            ValueError: If bucket_name or key is missing.
            ClientError: If the object does not exist or an unexpected error occurs.
        """
        if not bucket_name:
            raise ValueError("bucket_name is required.")
        if not key:
            raise ValueError("key is required.")
        self._cos.head_object(bucket=bucket_name, key=key)

    def get_presigned_url(self, *, bucket_name: str, key: str, expiry: int = 3600) -> str:
        """Generate a presigned GET URL for an object.

        Args:
            bucket_name: COS bucket name.
            key: Object key.
            expiry: URL validity in seconds (default 3600).

        Returns:
            Presigned URL string.

        Raises:
            ValueError: If bucket_name or key is missing.
        """
        if not bucket_name:
            raise ValueError("bucket_name is required.")
        if not key:
            raise ValueError("key is required.")
        return self._cos.generate_presigned_url(bucket=bucket_name, key=key, expiry=expiry)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd gateway && python -m pytest tests/core/services/ibm_cloud/code_engine/fleets/test_job_cos_unit.py -v
```

Expected: all pass (including pre-existing tests).

- [ ] **Step 5: Commit**

```bash
git add gateway/core/ibm_cloud/code_engine/fleets/cos.py gateway/tests/core/services/ibm_cloud/code_engine/fleets/test_job_cos_unit.py
git commit -m "Add head_object and get_presigned_url to JobCOS"
```

---

## Task 3: `LogsStorage` abstract interface + `RayLogsStorage` stubs

**Files:**
- Modify: `gateway/core/services/storage/logs_storage.py`
- Modify: `gateway/core/services/storage/logs_storage_ray.py`
- Test: `gateway/tests/core/services/storage/test_logs_storage.py`

- [ ] **Step 1: Write failing tests**

Append to `gateway/tests/core/services/storage/test_logs_storage.py`:

```python
    def test_get_public_logs_url_raises_not_implemented(self):
        """get_public_logs_url() raises NotImplementedError for Ray jobs."""
        job = self._create_job("auth1")
        with pytest.raises(NotImplementedError):
            RayLogsStorage(job).get_public_logs_url()

    def test_get_private_logs_url_raises_not_implemented(self):
        """get_private_logs_url() raises NotImplementedError for Ray provider jobs."""
        job = self._create_job("auth1", provider="provider1")
        with pytest.raises(NotImplementedError):
            RayLogsStorage(job).get_private_logs_url()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd gateway && python -m pytest tests/core/services/storage/test_logs_storage.py::TestLogsStorage::test_get_public_logs_url_raises_not_implemented tests/core/services/storage/test_logs_storage.py::TestLogsStorage::test_get_private_logs_url_raises_not_implemented -v
```

Expected: FAIL with `AttributeError` (method doesn't exist).

- [ ] **Step 3: Add abstract methods to `LogsStorage`**

In `gateway/core/services/storage/logs_storage.py`, append after `save_private_logs`:

```python
    @abstractmethod
    def get_public_logs_url(self) -> Optional[str]:
        """Return a presigned URL for public logs, or None if the object does not exist."""

    @abstractmethod
    def get_private_logs_url(self) -> Optional[str]:
        """Return a presigned URL for private logs, or None if the object does not exist."""
```

- [ ] **Step 4: Implement stubs in `RayLogsStorage`**

In `gateway/core/services/storage/logs_storage_ray.py`, append after `save_private_logs`:

```python
    def get_public_logs_url(self) -> Optional[str]:
        raise NotImplementedError("Presigned URLs are not supported for Ray jobs")

    def get_private_logs_url(self) -> Optional[str]:
        raise NotImplementedError("Presigned URLs are not supported for Ray jobs")
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd gateway && python -m pytest tests/core/services/storage/test_logs_storage.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add gateway/core/services/storage/logs_storage.py gateway/core/services/storage/logs_storage_ray.py gateway/tests/core/services/storage/test_logs_storage.py
git commit -m "Add get_public/private_logs_url to LogsStorage interface and Ray stub"
```

---

## Task 4: `FleetsLogsStorage` — presigned URL methods

**Files:**
- Modify: `gateway/core/services/storage/logs_storage_fleets.py`
- Test: `gateway/tests/core/services/storage/test_logs_storage_fleets.py`

- [ ] **Step 1: Write failing tests**

Append to the `TestFleetsLogsStorage` class in `gateway/tests/core/services/storage/test_logs_storage_fleets.py`:

```python
    # ── get_public_logs_url ────────────────────────────────────────────────────

    def test_get_public_logs_url_returns_url_when_object_exists(self, job):
        """get_public_logs_url() returns a presigned URL when the object exists."""
        storage = FleetsLogsStorage(job)
        mock_cos = MagicMock()
        mock_cos.get_presigned_url.return_value = "https://cos.example.com/logs.log?sig=abc"

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.get_public_logs_url()

        assert result == "https://cos.example.com/logs.log?sig=abc"
        mock_cos.head_object.assert_called_once_with(
            bucket_name="user-bucket",
            key=storage._public_key,  # pylint: disable=protected-access
        )
        mock_cos.get_presigned_url.assert_called_once_with(
            bucket_name="user-bucket",
            key=storage._public_key,  # pylint: disable=protected-access
        )

    def test_get_public_logs_url_returns_none_when_object_not_found(self, job):
        """get_public_logs_url() returns None when the log object does not exist in COS."""
        storage = FleetsLogsStorage(job)
        mock_cos = MagicMock()
        mock_cos.head_object.side_effect = _make_client_error("NoSuchKey")

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.get_public_logs_url()

        assert result is None
        mock_cos.get_presigned_url.assert_not_called()

    def test_get_public_logs_url_reraises_non_404_cos_error(self, job):
        """get_public_logs_url() re-raises unexpected COS errors (e.g., 403)."""
        storage = FleetsLogsStorage(job)
        mock_cos = MagicMock()
        mock_cos.head_object.side_effect = _make_client_error("AccessDenied")

        with patch(_COS_MODULE, return_value=mock_cos):
            with pytest.raises(ClientError):
                storage.get_public_logs_url()

    # ── get_private_logs_url ───────────────────────────────────────────────────

    def test_get_private_logs_url_returns_url_when_object_exists(self, job_with_provider):
        """get_private_logs_url() returns a presigned URL for provider jobs."""
        storage = FleetsLogsStorage(job_with_provider)
        mock_cos = MagicMock()
        mock_cos.get_presigned_url.return_value = "https://cos.example.com/private.log?sig=xyz"

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.get_private_logs_url()

        assert result == "https://cos.example.com/private.log?sig=xyz"
        mock_cos.head_object.assert_called_once_with(
            bucket_name="provider-bucket",
            key=storage._private_key,  # pylint: disable=protected-access
        )
        mock_cos.get_presigned_url.assert_called_once_with(
            bucket_name="provider-bucket",
            key=storage._private_key,  # pylint: disable=protected-access
        )

    def test_get_private_logs_url_returns_none_when_object_not_found(self, job_with_provider):
        """get_private_logs_url() returns None when the log object does not exist in COS."""
        storage = FleetsLogsStorage(job_with_provider)
        mock_cos = MagicMock()
        mock_cos.head_object.side_effect = _make_client_error("NotFound")

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.get_private_logs_url()

        assert result is None

    def test_get_private_logs_url_raises_for_custom_function(self, job):
        """get_private_logs_url() raises RuntimeError for non-provider jobs."""
        storage = FleetsLogsStorage(job)
        with pytest.raises(RuntimeError, match="provider jobs"):
            storage.get_private_logs_url()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd gateway && python -m pytest tests/core/services/storage/test_logs_storage_fleets.py::TestFleetsLogsStorage::test_get_public_logs_url_returns_url_when_object_exists tests/core/services/storage/test_logs_storage_fleets.py::TestFleetsLogsStorage::test_get_private_logs_url_returns_url_when_object_exists -v
```

Expected: FAIL.

- [ ] **Step 3: Implement in `FleetsLogsStorage`**

In `gateway/core/services/storage/logs_storage_fleets.py`, append these three methods after `save_private_logs`:

```python
    def get_public_logs_url(self) -> Optional[str]:
        if not self._object_exists(self._user_bucket, self._public_key):
            return None
        return get_cos_client(self._project).get_presigned_url(
            bucket_name=self._user_bucket,
            key=self._public_key,
        )

    def get_private_logs_url(self) -> Optional[str]:
        if self._provider_bucket is None:
            raise RuntimeError("Private logs are only available for provider jobs")
        if not self._object_exists(self._provider_bucket, self._private_key):
            return None
        return get_cos_client(self._project).get_presigned_url(
            bucket_name=self._provider_bucket,
            key=self._private_key,
        )

    def _object_exists(self, bucket: str, key: str) -> bool:
        try:
            get_cos_client(self._project).head_object(bucket_name=bucket, key=key)
            return True
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in self.NOT_FOUND_CODES:
                return False
            raise
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd gateway && python -m pytest tests/core/services/storage/test_logs_storage_fleets.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add gateway/core/services/storage/logs_storage_fleets.py gateway/tests/core/services/storage/test_logs_storage_fleets.py
git commit -m "Add presigned URL methods to FleetsLogsStorage"
```

---

## Task 5: `LogsResult` dataclass

**Files:**
- Create: `gateway/api/use_cases/jobs/logs_result.py`

- [ ] **Step 1: Create the file**

Create `gateway/api/use_cases/jobs/logs_result.py` with this content:

```python
"""Return type for log retrieval use cases."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LogsResult:
    """Discriminated result from log use cases.

    Exactly one of raw_log or redirect_url will be set, or neither (no logs yet).
    """

    raw_log: Optional[str] = field(default=None)
    redirect_url: Optional[str] = field(default=None)
```

- [ ] **Step 2: Commit**

```bash
git add gateway/api/use_cases/jobs/logs_result.py
git commit -m "Add LogsResult dataclass for log use case return type"
```

---

## Task 6: `get_logs` endpoint — use case + view + tests

This task updates `GetJobLogsUseCase` and the `get_logs` view atomically to avoid breaking existing tests. The use case now returns `LogsResult`; the view handles 302 (redirect), 204 (no logs), and 200 (Ray JSON).

**Files:**
- Modify: `gateway/api/use_cases/jobs/get_logs.py`
- Modify: `gateway/api/v1/views/jobs/get_logs.py`
- Modify: `gateway/tests/api/use_cases/jobs/test_logs_use_cases_fleets.py`
- Modify: `gateway/tests/api/test_logs.py`

- [ ] **Step 1: Update tests in `test_logs_use_cases_fleets.py`**

First, add this import at the **module level** (top of the file with the other imports):

```python
from api.use_cases.jobs.logs_result import LogsResult
```

Then replace the `TestGetJobLogsUseCaseFleet` class:

```python
class TestGetJobLogsUseCaseFleet:
    def _execute(self, job, user, cos_url=None):
        with patch(f"{_GET_LOGS_MOD}.get_logs_storage") as mock_storage:
            mock_storage.return_value.get_public_logs_url.return_value = cos_url
            return GetJobLogsUseCase().execute(job.id, user)

    def test_returns_redirect_url_when_logs_available(self, fleet_custom_job, author):
        """When COS object exists, use case returns LogsResult with redirect_url."""
        url = "https://cos.example.com/logs.log?sig=abc"
        result = self._execute(fleet_custom_job, author, cos_url=url)
        assert isinstance(result, LogsResult)
        assert result.redirect_url == url
        assert result.raw_log is None

    def test_returns_redirect_url_for_provider_job(self, fleet_provider_job, author):
        """Provider Fleet job: use case returns LogsResult with redirect_url."""
        url = "https://cos.example.com/provider-logs.log?sig=xyz"
        result = self._execute(fleet_provider_job, author, cos_url=url)
        assert isinstance(result, LogsResult)
        assert result.redirect_url == url

    def test_no_cos_logs_returns_empty_logs_result(self, fleet_custom_job, author):
        """When COS has no logs yet, returns LogsResult() with both fields None."""
        result = self._execute(fleet_custom_job, author, cos_url=None)
        assert isinstance(result, LogsResult)
        assert result.redirect_url is None
        assert result.raw_log is None

    def test_no_cos_logs_provider_job_returns_empty_logs_result(self, fleet_provider_job, author):
        """Provider Fleet job with no logs: returns LogsResult() with both fields None."""
        result = self._execute(fleet_provider_job, author, cos_url=None)
        assert isinstance(result, LogsResult)
        assert result.redirect_url is None
        assert result.raw_log is None
```

- [ ] **Step 2: Add view-level tests for Fleet responses to `test_logs.py`**

Append a new test class to `gateway/tests/api/test_logs.py`:

```python
from django.test import override_settings

@pytest.mark.django_db
class TestFleetJobLogsEndpoint:
    """Test /logs and /provider-logs view responses for Fleet jobs."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.client = APIClient()

    def _authorize(self, username):
        user, _ = User.objects.get_or_create(username=username)
        token = MagicMock()
        token.accessible_functions = FunctionAccessResult(use_legacy_authorization=True)
        self.client.force_authenticate(user=user, token=token)
        return user

    def _make_fleet_job(self, author_username):
        from core.models import CodeEngineProject
        ce_project = TestUtils.get_or_create_ce_project(
            project_name="test-project",
            project_id="test-ce-project-id",
            cos_bucket_user_data_name="user-bucket",
            cos_bucket_provider_data_name="provider-bucket",
            cos_instance_name="cos-instance",
            cos_key_name="cos-key",
        )
        program = TestUtils.create_program(
            program_title="fleet-func",
            author=author_username,
            runner=Program.FLEETS,
        )
        author, _ = User.objects.get_or_create(username=author_username)
        return TestUtils.create_job(author=author, program=program, code_engine_project=ce_project)

    @patch("api.use_cases.jobs.get_logs.get_logs_storage")
    def test_fleet_logs_returns_302_when_logs_exist(self, mock_storage):
        """Fleet /logs: 302 redirect when COS object exists."""
        presigned_url = "https://cos.example.com/logs.log?sig=abc"
        mock_storage.return_value.get_public_logs_url.return_value = presigned_url

        job = self._make_fleet_job("author")
        self._authorize("author")

        response = self.client.get(
            reverse("v1:jobs-logs", args=[str(job.id)]),
            format="json",
        )

        assert response.status_code == 302
        assert response["Location"] == presigned_url

    @patch("api.use_cases.jobs.get_logs.get_logs_storage")
    def test_fleet_logs_returns_204_when_no_logs(self, mock_storage):
        """Fleet /logs: 204 No Content when COS object does not exist yet."""
        mock_storage.return_value.get_public_logs_url.return_value = None

        job = self._make_fleet_job("author")
        self._authorize("author")

        response = self.client.get(
            reverse("v1:jobs-logs", args=[str(job.id)]),
            format="json",
        )

        assert response.status_code == 204
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd gateway && python -m pytest tests/api/use_cases/jobs/test_logs_use_cases_fleets.py::TestGetJobLogsUseCaseFleet tests/api/test_logs.py::TestFleetJobLogsEndpoint -v
```

Expected: FAIL (use case still returns `str`, view still calls `serialize_output(str)`).

- [ ] **Step 4: Update `GetJobLogsUseCase`**

Replace the entire content of `gateway/api/use_cases/jobs/get_logs.py`:

```python
"""
Use case: retrieve job logs.
"""

import logging
from uuid import UUID

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ObjectDoesNotExist

from api.access_policies.jobs import JobAccessPolicies
from api.domain.exceptions.job_not_found_exception import JobNotFoundException
from api.domain.exceptions.invalid_access_exception import InvalidAccessException
from api.use_cases.jobs.logs_result import LogsResult
from core.domain.filter_logs import remove_prefix_tags_in_logs, filter_logs_with_public_tags
from core.models import Job, Program
from core.services.runners import get_runner, RunnerError
from core.utils import check_logs
from core.services.storage import get_logs_storage

logger = logging.getLogger("api.GetJobLogsUseCase")


class GetJobLogsUseCase:
    """Use case for retrieving job logs."""

    def execute(self, job_id: UUID, user: AbstractUser) -> LogsResult:
        """Return the logs of a job if the user has access.

        Returns:
            LogsResult with redirect_url set (Fleet, logs ready),
            LogsResult() with both fields None (Fleet, no logs yet),
            or LogsResult with raw_log set (Ray).
        """
        try:
            job = Job.objects.get(id=job_id)
        except ObjectDoesNotExist:
            raise JobNotFoundException(job_id)

        if not JobAccessPolicies.can_read_user_logs(user, job):
            raise InvalidAccessException(f"You don't have access to read user logs of the job [{job_id}]")

        if job.program.runner == Program.FLEETS:
            logs_storage = get_logs_storage(job)
            url = logs_storage.get_public_logs_url()
            if url:
                logger.info("[jobs-logs] user_id=%s job_id=%s | Redirecting to presigned URL", user.id, job_id)
                return LogsResult(redirect_url=url)
            return LogsResult()

        # Ray path: try COS storage first, then active runner, then DB legacy
        logs_storage = get_logs_storage(job)
        logs = logs_storage.get_public_logs()
        if logs:
            return LogsResult(raw_log=logs)

        runner = get_runner(job)
        if runner.is_active():
            try:
                logs = runner.logs()
            except RunnerError:
                return LogsResult(raw_log="Logs not available for this job during execution.")

            logs = check_logs(logs, job)
            logger.info("Getting logs from runner=%s job_id=%s", job.program.runner, job.id)

            if job.program.provider:
                return LogsResult(raw_log=filter_logs_with_public_tags(logs))
            return LogsResult(raw_log=remove_prefix_tags_in_logs(logs))

        if job.program.provider:
            return LogsResult(raw_log="No logs available.")
        return LogsResult(raw_log=job.logs)
```

- [ ] **Step 5: Update `get_logs` view**

Replace the `get_logs` function in `gateway/api/v1/views/jobs/get_logs.py`:

```python
from django.http import HttpResponseRedirect
from rest_framework import permissions, serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api.use_cases.jobs.get_logs import GetJobLogsUseCase
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from api.v1.views.swagger_utils import standard_error_responses
```

Keep the existing imports and serializer/`serialize_output` unchanged. Replace only the `get_logs` function body:

```python
@swagger_auto_schema(
    method="get",
    operation_description="Retrieve logs for a given job.",
    responses={
        status.HTTP_200_OK: JobLogsOutputSerializer,
        **standard_error_responses(not_found_example="Job [XXXX] not found"),
    },
)
@endpoint("jobs/<uuid:job_id>/logs", name="jobs-logs")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def get_logs(request: Request, job_id: UUID) -> Response:
    """
    Retrieve logs for a specific job.

    Args:
        request: The HTTP request object.
        job_id: The UUID of the job (path parameter).

    Returns:
        302 redirect to presigned COS URL (Fleet, logs ready),
        204 No Content (Fleet, no logs yet),
        or 200 JSON with logs field (Ray).
    """
    user = cast(AbstractUser, request.user)
    result = GetJobLogsUseCase().execute(job_id, user)

    if result.redirect_url:
        logger.info("[jobs-logs] user_id=%s job_id=%s | Redirecting to presigned URL", user.id, job_id)
        return HttpResponseRedirect(result.redirect_url)

    if result.raw_log is None:
        return Response(status=status.HTTP_204_NO_CONTENT)

    logger.info("[jobs-logs] user_id=%s job_id=%s | Logs retrieved ok", user.id, job_id)
    return Response(serialize_output(result.raw_log))
```

Add `from django.http import HttpResponseRedirect` to the imports at the top.

- [ ] **Step 6: Run all affected tests**

```bash
cd gateway && python -m pytest tests/api/use_cases/jobs/test_logs_use_cases_fleets.py tests/api/test_logs.py -v
```

Expected: all pass. If `test_job_logs_in_storage_user_job` or similar Ray tests fail, they need the use case to return `LogsResult(raw_log=...)` — verify the Ray path in the updated use case.

- [ ] **Step 7: Commit**

```bash
git add gateway/api/use_cases/jobs/get_logs.py gateway/api/v1/views/jobs/get_logs.py gateway/tests/api/use_cases/jobs/test_logs_use_cases_fleets.py gateway/tests/api/test_logs.py
git commit -m "Update get_logs use case and view for Fleet presigned URL redirect"
```

---

## Task 7: `provider_logs` endpoint — use case + view + tests

Same pattern as Task 6, for the `/provider-logs` endpoint.

**Files:**
- Modify: `gateway/api/use_cases/jobs/provider_logs.py`
- Modify: `gateway/api/v1/views/jobs/provider_logs.py`
- Modify: `gateway/tests/api/use_cases/jobs/test_logs_use_cases_fleets.py`
- Modify: `gateway/tests/api/test_logs.py`

- [ ] **Step 1: Update `TestGetProviderJobLogsUseCaseFleet` in `test_logs_use_cases_fleets.py`**

Replace the class with this version:

```python
class TestGetProviderJobLogsUseCaseFleet:
    def _execute(self, job, user, cos_url=None, accessible_functions=None):
        with patch(f"{_PROVIDER_LOGS_MOD}.get_logs_storage") as mock_storage:
            mock_storage.return_value.get_private_logs_url.return_value = cos_url
            return GetProviderJobLogsUseCase().execute(job.id, user, accessible_functions=accessible_functions)

    def test_returns_redirect_url_when_logs_available(self, fleet_provider_job, provider_admin):
        """When COS private log exists, returns LogsResult with redirect_url."""
        url = "https://cos.example.com/private-logs.log?sig=xyz"
        result = self._execute(fleet_provider_job, provider_admin, cos_url=url)
        assert isinstance(result, LogsResult)
        assert result.redirect_url == url
        assert result.raw_log is None

    def test_no_cos_logs_returns_empty_logs_result(self, fleet_provider_job, provider_admin):
        """When COS has no private logs yet, returns LogsResult() with both fields None."""
        result = self._execute(fleet_provider_job, provider_admin, cos_url=None)
        assert isinstance(result, LogsResult)
        assert result.redirect_url is None
        assert result.raw_log is None

    def test_accessible_functions_grant_access(self, fleet_provider_job, author):
        """Provider logs accessible via FunctionAccessResult with correct permission."""
        accessible = create_function_access_result(
            "fleet-provider", "fleet-provider-func", {PLATFORM_PERMISSION_PROVIDER_LOGS}
        )
        url = "https://cos.example.com/private-logs.log?sig=granted"
        result = self._execute(fleet_provider_job, author, cos_url=url, accessible_functions=accessible)
        assert isinstance(result, LogsResult)
        assert result.redirect_url == url
```

- [ ] **Step 2: Add view-level tests for Fleet `/provider-logs` to `TestFleetJobLogsEndpoint` in `test_logs.py`**

Add these methods to the `TestFleetJobLogsEndpoint` class created in Task 6:

```python
    @patch("api.use_cases.jobs.provider_logs.get_logs_storage")
    def test_fleet_provider_logs_returns_302_when_logs_exist(self, mock_storage):
        """Fleet /provider-logs: 302 redirect when COS private log object exists."""
        presigned_url = "https://cos.example.com/private.log?sig=xyz"
        mock_storage.return_value.get_private_logs_url.return_value = presigned_url

        ce_project = TestUtils.get_or_create_ce_project(
            project_name="provider-project",
            project_id="provider-ce-project-id",
            cos_bucket_user_data_name="user-bucket",
            cos_bucket_provider_data_name="provider-bucket",
            cos_instance_name="cos-instance",
            cos_key_name="cos-key",
        )
        provider = TestUtils.get_or_create_provider("fleet-provider", "fleet-provider-group")
        program = TestUtils.create_program(
            program_title="provider-fleet-func",
            author="provider-author",
            provider=provider,
            runner=Program.FLEETS,
        )
        author, _ = User.objects.get_or_create(username="provider-author")
        job = TestUtils.create_job(author=author, program=program, code_engine_project=ce_project)

        admin, _ = User.objects.get_or_create(username="provider-admin-user")
        TestUtils.add_user_to_group("provider-admin-user", "fleet-provider-group")

        token = MagicMock()
        token.accessible_functions = FunctionAccessResult(use_legacy_authorization=True)
        self.client.force_authenticate(user=admin, token=token)

        response = self.client.get(
            reverse("v1:jobs-provider-logs", args=[str(job.id)]),
            format="json",
        )

        assert response.status_code == 302
        assert response["Location"] == presigned_url

    @patch("api.use_cases.jobs.provider_logs.get_logs_storage")
    def test_fleet_provider_logs_returns_204_when_no_logs(self, mock_storage):
        """Fleet /provider-logs: 204 No Content when COS private log does not exist yet."""
        mock_storage.return_value.get_private_logs_url.return_value = None

        ce_project = TestUtils.get_or_create_ce_project(
            project_name="provider-project-2",
            project_id="provider-ce-project-id-2",
            cos_bucket_user_data_name="user-bucket",
            cos_bucket_provider_data_name="provider-bucket",
            cos_instance_name="cos-instance",
            cos_key_name="cos-key",
        )
        provider = TestUtils.get_or_create_provider("fleet-provider-2", "fleet-provider-group-2")
        program = TestUtils.create_program(
            program_title="provider-fleet-func-2",
            author="provider-author-2",
            provider=provider,
            runner=Program.FLEETS,
        )
        author, _ = User.objects.get_or_create(username="provider-author-2")
        job = TestUtils.create_job(author=author, program=program, code_engine_project=ce_project)

        admin, _ = User.objects.get_or_create(username="provider-admin-user-2")
        TestUtils.add_user_to_group("provider-admin-user-2", "fleet-provider-group-2")

        token = MagicMock()
        token.accessible_functions = FunctionAccessResult(use_legacy_authorization=True)
        self.client.force_authenticate(user=admin, token=token)

        response = self.client.get(
            reverse("v1:jobs-provider-logs", args=[str(job.id)]),
            format="json",
        )

        assert response.status_code == 204
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd gateway && python -m pytest tests/api/use_cases/jobs/test_logs_use_cases_fleets.py::TestGetProviderJobLogsUseCaseFleet tests/api/test_logs.py::TestFleetJobLogsEndpoint::test_fleet_provider_logs_returns_302_when_logs_exist -v
```

Expected: FAIL.

- [ ] **Step 4: Update `GetProviderJobLogsUseCase`**

Replace the entire content of `gateway/api/use_cases/jobs/provider_logs.py`:

```python
"""
Use case: retrieve job logs.
"""

import logging
from typing import Optional
from uuid import UUID

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ObjectDoesNotExist

from api.access_policies.jobs import JobAccessPolicies
from api.domain.exceptions.job_not_found_exception import JobNotFoundException
from api.domain.exceptions.invalid_access_exception import InvalidAccessException
from api.use_cases.jobs.logs_result import LogsResult
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.domain.filter_logs import filter_logs_with_non_public_tags
from core.models import Job, Program
from core.utils import check_logs
from core.services.runners import get_runner, RunnerError
from core.services.storage import get_logs_storage

logger = logging.getLogger("api.GetProviderJobLogsUseCase")


class GetProviderJobLogsUseCase:
    """Use case for retrieving job logs."""

    def execute(
        self,
        job_id: UUID,
        user: AbstractUser,
        accessible_functions: Optional[FunctionAccessResult] = None,
    ) -> LogsResult:
        """Return the provider logs of a job if the user has access.

        Returns:
            LogsResult with redirect_url set (Fleet, logs ready),
            LogsResult() with both fields None (Fleet, no logs yet),
            or LogsResult with raw_log set (Ray).
        """
        try:
            job = Job.objects.get(id=job_id)
        except ObjectDoesNotExist:
            raise JobNotFoundException(job_id)

        if not JobAccessPolicies.can_read_provider_logs(user, job, accessible_functions=accessible_functions):
            raise InvalidAccessException(f"You don't have access to job [{job_id}]")

        if job.program.runner == Program.FLEETS:
            logs_storage = get_logs_storage(job)
            url = logs_storage.get_private_logs_url()
            if url:
                logger.info(
                    "[jobs-provider-logs] user_id=%s job_id=%s | Redirecting to presigned URL",
                    user.id,
                    job_id,
                )
                return LogsResult(redirect_url=url)
            return LogsResult()

        # Ray path
        logs_storage = get_logs_storage(job)
        logs = logs_storage.get_private_logs()
        if logs:
            return LogsResult(raw_log=logs)

        runner = get_runner(job)
        if runner.is_active():
            try:
                logs = runner.provider_logs()
            except RunnerError:
                logger.warning(
                    "[get-provider-logs] job_id=%s user_id=%s runner=%s | Failed to get provider logs",
                    job.id,
                    user.id,
                    job.program.runner,
                )
                return LogsResult(raw_log=f"Logs not available for job [{job_id}] during execution.")

            logger.info(
                "[get-provider-logs] job_id=%s user_id=%s runner=%s | Got provider logs from runner",
                job.id,
                user.id,
                job.program.runner,
            )
            logs = check_logs(logs, job)
            return LogsResult(raw_log=filter_logs_with_non_public_tags(logs))

        return LogsResult(raw_log=job.logs)
```

- [ ] **Step 5: Update `provider_logs` view**

Replace the `provider_logs` function in `gateway/api/v1/views/jobs/provider_logs.py`. Add `from django.http import HttpResponseRedirect` to imports. Replace the function body:

```python
@swagger_auto_schema(
    method="get",
    operation_description="Retrieve logs for a given job as provider.",
    responses={
        status.HTTP_200_OK: JobProviderLogsOutputSerializer,
        **standard_error_responses(not_found_example="Job [XXXX] not found"),
    },
)
@endpoint("jobs/<uuid:job_id>/provider-logs", name="jobs-provider-logs")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def provider_logs(request: Request, job_id: UUID) -> Response:
    """
    Retrieve provider logs for a specific job.

    Returns:
        302 redirect to presigned COS URL (Fleet, logs ready),
        204 No Content (Fleet, no logs yet),
        or 200 JSON with logs field (Ray).
    """
    user = cast(AbstractUser, request.user)
    accessible_functions = cast(FunctionAccessResult, request.auth.accessible_functions)
    logger.info(
        "[jobs-provider-logs] user_id=%s job_id=%s accessible_functions=%s",
        user.id,
        job_id,
        accessible_functions,
    )
    result = GetProviderJobLogsUseCase().execute(job_id, user, accessible_functions=accessible_functions)

    if result.redirect_url:
        logger.info("[jobs-provider-logs] user_id=%s job_id=%s | Redirecting to presigned URL", user.id, job_id)
        return HttpResponseRedirect(result.redirect_url)

    if result.raw_log is None:
        return Response(status=status.HTTP_204_NO_CONTENT)

    logger.info("[jobs-provider-logs] user_id=%s job_id=%s | Provider logs retrieved ok", user.id, job_id)
    return Response(serialize_output(result.raw_log))
```

- [ ] **Step 6: Run all affected tests**

```bash
cd gateway && python -m pytest tests/api/use_cases/jobs/test_logs_use_cases_fleets.py tests/api/test_logs.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add gateway/api/use_cases/jobs/provider_logs.py gateway/api/v1/views/jobs/provider_logs.py gateway/tests/api/use_cases/jobs/test_logs_use_cases_fleets.py gateway/tests/api/test_logs.py
git commit -m "Update provider_logs use case and view for Fleet presigned URL redirect"
```

---

## Task 8: Python client — handle redirect and 204

**Files:**
- Modify: `client/qiskit_serverless/core/clients/serverless_client.py`
- Modify: `client/tests/core/test_serverless_client_jobs.py`

- [ ] **Step 1: Add failing tests to `TestLogsMethod`**

In `client/tests/core/test_serverless_client_jobs.py`, append to the `TestLogsMethod` class:

```python
    def test_logs_returns_text_after_redirect(self, mock_client):
        """logs() returns response.text when the gateway redirects to a presigned URL."""
        log_content = "line one\nline two\n"

        with requests_mock.Mocker() as mocker:
            # The presigned URL endpoint returns plain text
            presigned_url = "https://cos.example.com/logs.log?sig=abc"
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/logs/",
                status_code=302,
                headers={"Location": presigned_url},
            )
            mocker.get(presigned_url, text=log_content)

            logs = mock_client.logs("test-job")

            assert logs == log_content

    def test_logs_returns_none_on_204(self, mock_client):
        """logs() returns None when the gateway responds with 204 No Content."""
        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/logs/",
                status_code=204,
            )

            logs = mock_client.logs("test-job")

            assert logs is None
```

Append to the `TestProviderLogsMethod` class:

```python
    def test_provider_logs_returns_text_after_redirect(self, mock_client):
        """provider_logs() returns response.text when the gateway redirects."""
        log_content = "private line one\n"

        with requests_mock.Mocker() as mocker:
            presigned_url = "https://cos.example.com/private.log?sig=xyz"
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/provider-logs/",
                status_code=302,
                headers={"Location": presigned_url},
            )
            mocker.get(presigned_url, text=log_content)

            logs = mock_client.provider_logs("test-job")

            assert logs == log_content

    def test_provider_logs_returns_none_on_204(self, mock_client):
        """provider_logs() returns None when the gateway responds with 204 No Content."""
        with requests_mock.Mocker() as mocker:
            mocker.get(
                "https://test-host.com/api/v1/jobs/test-job/provider-logs/",
                status_code=204,
            )

            logs = mock_client.provider_logs("test-job")

            assert logs is None
```

- [ ] **Step 2: Run failing tests**

```bash
cd client && python -m pytest tests/core/test_serverless_client_jobs.py::TestLogsMethod::test_logs_returns_text_after_redirect tests/core/test_serverless_client_jobs.py::TestLogsMethod::test_logs_returns_none_on_204 -v
```

Expected: FAIL (current `logs()` tries to JSON-parse the redirect response body).

- [ ] **Step 3: Update `logs()` and `provider_logs()` in `serverless_client.py`**

Find and replace the `logs` method (around line 425):

```python
@_trace_job
def logs(self, job_id: str):
    response = requests.get(
        f"{self.host}/api/{self.version}/jobs/{job_id}/logs/",
        headers=get_headers(token=self.token, instance=self.instance, channel=self.channel),
        timeout=REQUESTS_TIMEOUT,
    )
    if response.status_code == 204:
        return None
    if response.history:  # Followed a redirect to presigned COS URL
        return response.text
    return safe_json_request_as_dict(request=lambda: response).get("logs")
```

Find and replace the `provider_logs` method (around line 436):

```python
@_trace_job
def provider_logs(self, job_id: str):
    response = requests.get(
        f"{self.host}/api/{self.version}/jobs/{job_id}/provider-logs/",
        headers=get_headers(token=self.token, instance=self.instance, channel=self.channel),
        timeout=REQUESTS_TIMEOUT,
    )
    if response.status_code == 204:
        return None
    if response.history:  # Followed a redirect to presigned COS URL
        return response.text
    return safe_json_request_as_dict(request=lambda: response).get("logs")
```

- [ ] **Step 4: Run full client test suite for logs**

```bash
cd client && python -m pytest tests/core/test_serverless_client_jobs.py::TestLogsMethod tests/core/test_serverless_client_jobs.py::TestProviderLogsMethod -v
```

Expected: all pass (including pre-existing tests).

- [ ] **Step 5: Commit**

```bash
git add client/qiskit_serverless/core/clients/serverless_client.py client/tests/core/test_serverless_client_jobs.py
git commit -m "Update client logs() and provider_logs() to handle 302 redirect and 204"
```

---

## Final Verification

- [ ] **Run the full gateway test suite**

```bash
cd gateway && python -m pytest -v
```

Expected: all tests pass.

- [ ] **Run the full client test suite**

```bash
cd client && python -m pytest -v
```

Expected: all tests pass.
