# Fleet Logs: Presigned URL Redirect

## Context

Currently, log downloads for Fleet jobs route the full file content through the gateway: the gateway fetches the object from IBM Cloud Object Storage (COS) via boto3 into memory, then sends it to the client as a JSON response. This wastes gateway memory and bandwidth for every log download.

For Ray jobs this is unavoidable — COS is mounted as a volume and accessed via the filesystem. For Fleet jobs, however, the gateway already has a boto3 HMAC client with full COS access, which means it can generate presigned URLs. The goal is to remove the gateway from the data path by redirecting the client directly to a time-limited presigned COS URL.

## Architecture

```
Client                    Gateway                     IBM COS
  |                          |                            |
  |  GET /jobs/{id}/logs     |                            |
  |------------------------->|                            |
  |                          |  HEAD object (exists?)     |
  |                          |--------------------------->|
  |                          |<---------------------------|
  |                          |  generate_presigned_url()  |
  |  302 Location: <url>     |                            |
  |<-------------------------|                            |
  |  GET <presigned_url>                                  |
  |------------------------------------------------------>|
  |  200 raw log text                                     |
  |<------------------------------------------------------|
```

For Ray jobs the flow is unchanged (200 JSON with `{"logs": "..."}`). For Fleet jobs when no log object exists yet, the endpoint returns 204 No Content.

## Components and Changes

### 1. `COSClient` — `gateway/core/ibm_cloud/cos/cos_client.py`

New method:
```python
def generate_presigned_url(self, *, bucket: str, key: str, expiry: int = 3600) -> str:
    return self._s3_hmac.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expiry,
    )

def head_object(self, *, bucket: str, key: str) -> None:
    """Raises ClientError if object does not exist."""
    self._s3_hmac.head_object(Bucket=bucket, Key=key)
```

### 2. `JobCOS` — `gateway/core/ibm_cloud/code_engine/fleets/cos.py`

New methods delegating to `COSClient`:
```python
def get_presigned_url(self, *, bucket_name: str, key: str, expiry: int = 3600) -> str:
    return self._cos.generate_presigned_url(bucket=bucket_name, key=key, expiry=expiry)

def head_object(self, *, bucket_name: str, key: str) -> None:
    self._cos.head_object(bucket=bucket_name, key=key)
```

### 3. `LogsStorage` (abstract) — `gateway/core/services/storage/logs_storage.py`

Two new abstract methods:
```python
@abstractmethod
def get_public_logs_url(self) -> Optional[str]: ...

@abstractmethod
def get_private_logs_url(self) -> Optional[str]: ...
```

### 4. `RayLogsStorage` — `gateway/core/services/storage/logs_storage_ray.py`

```python
def get_public_logs_url(self) -> Optional[str]:
    raise NotImplementedError("Presigned URLs are not supported for Ray jobs")

def get_private_logs_url(self) -> Optional[str]:
    raise NotImplementedError("Presigned URLs are not supported for Ray jobs")
```

### 5. `FleetsLogsStorage` — `gateway/core/services/storage/logs_storage_fleets.py`

```python
def get_public_logs_url(self) -> Optional[str]:
    if not self._object_exists(self._user_bucket, self._public_key):
        return None
    return get_cos_client(self._project).get_presigned_url(
        bucket_name=self._user_bucket, key=self._public_key
    )

def get_private_logs_url(self) -> Optional[str]:
    if self._provider_bucket is None:
        raise RuntimeError("Private logs are only available for provider jobs")
    if not self._object_exists(self._provider_bucket, self._private_key):
        return None
    return get_cos_client(self._project).get_presigned_url(
        bucket_name=self._provider_bucket, key=self._private_key
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

### 6. Use cases — `gateway/api/use_cases/jobs/`

New shared dataclass in `gateway/api/use_cases/jobs/logs_result.py`, imported by both use cases:
```python
@dataclass
class LogsResult:
    raw_log: Optional[str] = None
    redirect_url: Optional[str] = None
```

`GetJobLogsUseCase.execute()` — Fleet branch replaces current logic:
```python
logs_storage = get_logs_storage(job)
url = logs_storage.get_public_logs_url()
if url:
    return LogsResult(redirect_url=url)
return LogsResult()  # → 204
```

Ray path wraps its existing string return in `LogsResult(raw_log=logs)`.

Same pattern in `GetProviderJobLogsUseCase`, using `get_private_logs_url()`.

### 7. Views — `gateway/api/v1/views/jobs/get_logs.py` and `provider_logs.py`

```python
result = GetJobLogsUseCase().execute(job_id, user)

if result.redirect_url:
    return HttpResponseRedirect(result.redirect_url)  # 302

if result.raw_log is None:
    return Response(status=status.HTTP_204_NO_CONTENT)

return Response(serialize_output(result.raw_log))  # 200 JSON (Ray)
```

### 8. Python client — `client/qiskit_serverless/core/clients/serverless_client.py`

`logs()` and `provider_logs()` make the request explicitly instead of going through `safe_json_request_as_dict` directly:

```python
def logs(self, job_id: str):
    response = requests.get(
        f"{self.host}/api/{self.version}/jobs/{job_id}/logs/",
        headers=get_headers(token=self.token, instance=self.instance, channel=self.channel),
        timeout=REQUESTS_TIMEOUT,
    )
    if response.status_code == 204:
        return None
    if response.history:  # Followed a redirect → raw log text from COS
        return response.text
    return safe_json_request_as_dict(request=lambda: response).get("logs")
```

Same pattern for `provider_logs()`.

## Data Flow Summary

| Case | Gateway response | Client receives |
|------|-----------------|-----------------|
| Fleet job, logs ready | `302 Location: <presigned_url>` | Raw log text (after auto-redirect) |
| Fleet job, no logs yet | `204 No Content` | `None` |
| Ray job (any state) | `200 {"logs": "..."}` | Log string (unchanged) |

## Error Handling

- Presigned URL generation failure (e.g. HMAC credentials issue) → unhandled exception → 500 (same as current boto3 errors)
- `_object_exists` returns `False` for NOT_FOUND codes (404, NoSuchKey, NotFound), re-raises on other `ClientError` (403, 500, etc.) → propagates as 500

## Testing

**Gateway unit tests:**
- `test_logs_storage_fleets.py`: mock `get_cos_client`; assert `get_public_logs_url()` returns URL when object exists, `None` when 404
- `test_logs_storage_ray.py`: assert `get_public_logs_url()` raises `NotImplementedError`
- `test_get_logs_use_case.py` / `test_provider_logs_use_case.py`: mock storage; assert `LogsResult.redirect_url` set for Fleets, `LogsResult.raw_log` set for Ray
- `test_get_logs_view.py` / `test_provider_logs_view.py`: assert 302 with `Location`, 204, and 200 responses

**Client unit tests:**
- `response.history` non-empty → returns `response.text`
- `response.status_code == 204` → returns `None`
- Normal 200 JSON → returns `response_data.get("logs")`

**Manual verification:**
1. Launch a Fleet job → call `GET /jobs/{id}/logs` during execution → expect 204
2. After completion → expect 302 with `Location` pointing to COS presigned URL
3. Python client returns the log content correctly
4. Provider job → same with `/provider-logs` pointing to provider bucket
