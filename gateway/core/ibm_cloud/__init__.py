"""IBM Cloud integration package."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.conf import settings
from urllib3.exceptions import MaxRetryError, NameResolutionError, ProtocolError, ReadTimeoutError
from urllib3.util.retry import Retry

from core.domain.exceptions.retryable_error import RetryableError
from core.ibm_cloud import call_metrics
from core.ibm_cloud.clients import IBMCloudClientProvider, COS_PUBLIC_URL_TEMPLATE
from core.ibm_cloud.code_engine.ce_client import ApiClient, Configuration, SecretsAndConfigmapsApi
from core.ibm_cloud.code_engine.ce_client.rest import ApiException
from core.ibm_cloud.cos.cos_client import COSClient, CosHmacCredentials
from core.ibm_cloud.code_engine.fleets.cos import JobCOS

if TYPE_CHECKING:
    from core.models import CodeEngineProject

_COS_CLIENT_TTL_SECONDS = 60
_cos_clients: dict[tuple, tuple[JobCOS, float]] = {}
_cos_clients_lock = threading.Lock()

# (connect, read) seconds for the HMAC secret read. Deliberately tighter than the IAM budget: the IAM
# fetch above it already costs up to 8s of the 25s a gunicorn request gets.
_SECRET_TIMEOUT_SECONDS = (1, 3)


@dataclass(frozen=True)
class CEAuth:
    """Authenticated Code Engine session."""

    api_client: ApiClient
    client_provider: IBMCloudClientProvider


def get_ce_auth(api_key: str, region: str, *, retry_reads: bool = True) -> CEAuth:
    """Create an authenticated CE ApiClient and IBMCloudClientProvider.

    Args:
        api_key: IBM Cloud API key.
        region: IBM Cloud region (e.g. ``"us-south"``).
        retry_reads: ``False`` raises a timed-out read, and returns a 429, on the first try.

    Returns:
        :class:`CEAuth` holding the CE API client and the client provider.
    """
    client_provider = IBMCloudClientProvider(api_key=api_key, region=region)
    cfg = Configuration()
    cfg.host = client_provider.config.code_engine_url
    # Configuration uses a copy-on-call singleton; replace the shared dict references
    # so different ApiClient instances don't mutate each other's credentials.
    cfg.api_key = {}
    cfg.api_key_prefix = {"Authorization": "Bearer"}

    # get_api_key_with_prefix is the only reader of api_key and it calls this first, so the token
    # is read per request. That is why api_key starts empty.
    def refresh_token(config: Configuration) -> None:
        config.api_key["Authorization"] = client_provider.tokens.get_token()

    cfg.refresh_api_key_hook = refresh_token
    api_client = _MeteredApiClient(cfg)
    # urllib3 retries a timed-out read on a DELETE 3 times, which holds the single-threaded scheduler 4x its timeout
    api_client.rest_client.pool_manager.connection_pool_kw["retries"] = Retry.DEFAULT.new(
        allowed_methods=Retry.DEFAULT_ALLOWED_METHODS - {"DELETE"},
        read=None if retry_reads else False,
        respect_retry_after_header=retry_reads,
    )
    return CEAuth(api_client=api_client, client_provider=client_provider)


class _MeteredApiClient(ApiClient):
    """An ApiClient that reports the time and the result of each Code Engine call."""

    def call_api(self, resource_path, method, *args, **kwargs):
        start = time.monotonic()
        status = "ok"
        try:
            return super().call_api(resource_path, method, *args, **kwargs)
        except ApiException as exc:
            status = str(exc.status or 0)
            raise
        except Exception as exc:
            status = type(exc).__name__
            raise
        finally:
            call_metrics.observe_code_engine(f"{method} {resource_path}", status, time.monotonic() - start)


def get_cos_client(project: CodeEngineProject) -> JobCOS:
    """Build a :class:`JobCOS` for the given CE project, reused in this process for 60 seconds.

    Reads ``IBM_CLOUD_API_KEY``, ``CE_HMAC_SECRET_NAME``, and
    ``CE_COS_USE_PUBLIC_ENDPOINT`` from Django settings, fetches HMAC
    credentials from the named CE secret, and returns a ready :class:`JobCOS`.

    Construction is delegated to :func:`_create_cos_client`. That private
    indirection is the single seam tests patch: callers do
    ``from core.ibm_cloud import get_cos_client`` (binding their own name), but
    this function resolves ``_create_cos_client`` via the module namespace at
    call time, so one patch of the private helper redirects every caller.

    Args:
        project: Active :class:`CodeEngineProject` whose region and project_id
            are used to authenticate and locate the CE secret.

    Returns:
        Initialized :class:`JobCOS`.

    Raises:
        ValueError: If required settings are missing or the CE secret is not
            found / lacks the expected HMAC fields.
        RetryableError: If Code Engine or IAM answers 429 or 5xx, or does not answer in time.
        ApiException: If the CE secrets API call fails for any other reason.
    """
    key = (project.project_id, project.region)
    now = time.monotonic()
    with _cos_clients_lock:
        cached = _cos_clients.get(key)
    if cached and now - cached[1] < _COS_CLIENT_TTL_SECONDS:
        return cached[0]
    client = _create_cos_client(project)
    with _cos_clients_lock:
        _cos_clients[key] = (client, now)
    return client


def clear_cos_clients() -> None:
    """Drop every cached COS client."""
    with _cos_clients_lock:
        _cos_clients.clear()


def _create_cos_client(project: CodeEngineProject) -> JobCOS:
    """Construct the real :class:`JobCOS` (see :func:`get_cos_client`).

    Args:
        project: Active :class:`CodeEngineProject` to authenticate against.

    Returns:
        Initialized :class:`JobCOS`.
    """
    api_key = settings.IBM_CLOUD_API_KEY
    if not api_key:
        raise ValueError("IBM_CLOUD_API_KEY not configured")

    hmac_secret_name = settings.CE_HMAC_SECRET_NAME
    if not hmac_secret_name:
        raise ValueError("CE_HMAC_SECRET_NAME not configured")

    ce_auth = get_ce_auth(api_key, project.region)

    secrets_api = SecretsAndConfigmapsApi(ce_auth.api_client)
    try:
        secret = secrets_api.get_secret(
            project_id=project.project_id, name=hmac_secret_name, _request_timeout=_SECRET_TIMEOUT_SECONDS
        )
    except ApiException as exc:
        if exc.status == 404:
            raise ValueError(f"CE secret {hmac_secret_name!r} not found in project {project.project_id!r}") from exc
        # status 0 is the vendored client's answer when the request never left or came back unreadable
        status = exc.status or 0
        if status in (0, 429) or status >= 500:
            raise RetryableError(f"Code Engine API error: {exc.reason}", status_code=status) from exc
        raise
    except MaxRetryError as exc:
        # a host that does not resolve is configuration, not a blip
        if isinstance(exc.reason, NameResolutionError):
            raise
        raise RetryableError("Unable to reach Code Engine") from exc
    except (ReadTimeoutError, ProtocolError) as exc:
        raise RetryableError("Unable to reach Code Engine") from exc

    data: dict[str, Any] = secret.data if isinstance(secret.data, dict) else {}
    access_key_id = data.get("access_key_id", "")
    secret_access_key = data.get("secret_access_key", "")

    if not access_key_id or not secret_access_key:
        raise ValueError(f"CE secret {hmac_secret_name!r} is missing 'access_key_id' or 'secret_access_key'")

    endpoint_url = None
    if settings.CE_COS_USE_PUBLIC_ENDPOINT:
        endpoint_url = COS_PUBLIC_URL_TEMPLATE.format(region=project.region)

    cos_client = COSClient(
        client_provider=ce_auth.client_provider,
        credentials=CosHmacCredentials(
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
        ),
        bucket_region=project.region,
        endpoint_url=endpoint_url,
    )
    return JobCOS(cos_client)


__all__ = ["CEAuth", "get_ce_auth", "get_cos_client", "JobCOS"]
