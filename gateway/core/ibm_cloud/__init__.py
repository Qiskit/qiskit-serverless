"""IBM Cloud integration package."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.conf import settings

from core.ibm_cloud.clients import IBMCloudClientProvider, COS_PUBLIC_URL_TEMPLATE
from core.ibm_cloud.code_engine.ce_client import ApiClient, Configuration, SecretsAndConfigmapsApi
from core.ibm_cloud.code_engine.ce_client.rest import ApiException
from core.ibm_cloud.cos.cos_client import COSClient, CosHmacCredentials
from core.ibm_cloud.code_engine.fleets.cos import JobCOS

if TYPE_CHECKING:
    from core.models import CodeEngineProject


@dataclass(frozen=True)
class CEAuth:
    """Authenticated Code Engine session."""

    api_client: ApiClient
    client_provider: IBMCloudClientProvider


def get_ce_auth(api_key: str, region: str) -> CEAuth:
    """Create an authenticated CE ApiClient and IBMCloudClientProvider.

    Args:
        api_key: IBM Cloud API key.
        region: IBM Cloud region (e.g. ``"us-south"``).

    Returns:
        :class:`CEAuth` holding the CE API client and the client provider.
    """
    client_provider = IBMCloudClientProvider(api_key=api_key, region=region)
    cfg = Configuration()
    cfg.host = client_provider.config.code_engine_url
    # Configuration uses a copy-on-call singleton; replace the shared dict references
    # so different ApiClient instances don't mutate each other's credentials.
    cfg.api_key = {"Authorization": client_provider.auth.token}
    cfg.api_key_prefix = {"Authorization": "Bearer"}
    return CEAuth(api_client=ApiClient(cfg), client_provider=client_provider)


def get_cos_client(project: CodeEngineProject) -> JobCOS:
    """Build a :class:`JobCOS` for the given CE project.

    Reads ``IBM_CLOUD_API_KEY``, ``CE_HMAC_SECRET_NAME``, and
    ``CE_COS_USE_PUBLIC_ENDPOINT`` from Django settings, fetches HMAC
    credentials from the named CE secret, and returns a ready :class:`JobCOS`.

    Args:
        project: Active :class:`CodeEngineProject` whose region and project_id
            are used to authenticate and locate the CE secret.

    Returns:
        Initialized :class:`JobCOS`.

    Raises:
        ValueError: If required settings are missing or the CE secret is not
            found / lacks the expected HMAC fields.
        ApiException: If the CE secrets API call fails for a non-404 reason.
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
        secret = secrets_api.get_secret(project_id=project.project_id, name=hmac_secret_name)
    except ApiException as exc:
        if exc.status == 404:
            raise ValueError(f"CE secret {hmac_secret_name!r} not found in project {project.project_id!r}") from exc
        raise

    data: dict[str, Any] = secret.data if isinstance(secret.data, dict) else {}
    access_key_id = data.get("access_key_id", "")
    secret_access_key = data.get("secret_access_key", "")

    if not access_key_id or not secret_access_key:
        raise ValueError(f"CE secret {hmac_secret_name!r} is missing 'access_key_id' or 'secret_access_key'")

    endpoint_url = None
    if getattr(settings, "CE_COS_USE_PUBLIC_ENDPOINT", False):
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
