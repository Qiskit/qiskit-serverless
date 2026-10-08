"""Client for the Runtime API's ``PUT /functions/{function_id}``, which mirrors a Functions job to the Runtime API as
a workload.

One attempt per call and no internal retry: the caller decides what a failure means, and ``RuntimeApiError.retryable``
tells it whether trying again can help.
"""

import logging

import requests
from django.conf import settings
from ibm_cloud_sdk_core import ApiException
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator

from core.config_key import ConfigKey
from core.domain.crn import regional_base_url
from core.models import Config

logger = logging.getLogger("gateway.clients.runtime_api")

_RETRYABLE_CLIENT_ERRORS = {408, 429}
_KEY_REJECTED = {400, 401, 403}


class RuntimeApiError(Exception):
    """The Runtime API call failed. ``retryable`` is True when trying again later can succeed."""

    def __init__(self, message: str, *, retryable: bool, status_code: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class RuntimeApiConfigError(RuntimeApiError):
    """The mirror is on but the deployment is not configured for it. Retrying cannot fix it."""

    def __init__(self, message: str):
        super().__init__(message, retryable=False)


class RuntimeApiClient:
    """Sends the envelope built by ``core.domain.workload_payload.build_workload_payload``.

    Create one instance per process and keep it: each instance has its own IAM token manager and cache, so building
    one per request would ask IAM for a new token every time."""

    def __init__(self) -> None:
        self._authenticator: IAMAuthenticator | None = None

    def _token(self) -> str:
        """A valid IAM token. The SDK's token manager caches it and refreshes it near expiry, so ask on every call.
        Raises RuntimeApiConfigError when the key itself is the problem and RuntimeApiError (retryable) otherwise."""
        if self._authenticator is None:
            try:
                authenticator = IAMAuthenticator(
                    settings.FUNCTIONS_OPERATOR_API_KEY, url=settings.IAM_IBM_CLOUD_BASE_URL
                )
            except ValueError as exc:  # the SDK raises ValueError only from this constructor
                logger.error("FUNCTIONS_OPERATOR_API_KEY was rejected by the IAM client: %s", type(exc).__name__)
                raise RuntimeApiConfigError("FUNCTIONS_OPERATOR_API_KEY is malformed") from exc
            # The token manager waits 60 s by default, far above the budget of one mirror call.
            authenticator.token_manager.http_config = {"timeout": settings.WORKLOADS_MIRROR_TIMEOUT}
            self._authenticator = authenticator
        try:
            return self._authenticator.token_manager.get_token()
        except ApiException as exc:
            if exc.status_code in _KEY_REJECTED:
                logger.error("IAM rejected FUNCTIONS_OPERATOR_API_KEY with status %s", exc.status_code)
                raise RuntimeApiConfigError(
                    f"IAM rejected FUNCTIONS_OPERATOR_API_KEY (status {exc.status_code})"
                ) from exc
            logger.error("Could not get an IAM token, status %s", exc.status_code)
            raise RuntimeApiError("Could not get an IAM token", retryable=True) from exc
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Could not get an IAM token: %s", type(exc).__name__)
            raise RuntimeApiError("Could not get an IAM token", retryable=True) from exc

    def put_function(self, payload: dict) -> None:
        """Send ``payload`` to the Runtime API. Returns when it applied it (200) or ignored it because the function was
        already terminal (202). Does nothing at all while ``workloads.mirror.enabled`` is off. Raises
        RuntimeApiConfigError if it is on and FUNCTIONS_OPERATOR_API_KEY is empty, and RuntimeApiError otherwise."""
        if not Config.get_bool(ConfigKey.WORKLOADS_MIRROR_ENABLED):
            return
        if not settings.FUNCTIONS_OPERATOR_API_KEY:
            raise RuntimeApiConfigError("workloads.mirror.enabled is on but FUNCTIONS_OPERATOR_API_KEY is not set")

        function_id, body = payload["function_id"], payload["body"]
        base_url = regional_base_url(
            settings.RUNTIME_API_BASE_URL, body.get("crn"), settings.RUNTIME_API_DEFAULT_REGION
        )
        token = self._token()

        try:
            response = requests.put(
                f"{base_url}/api/v1/functions/{function_id}",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
                timeout=settings.WORKLOADS_MIRROR_TIMEOUT,
            )
        except requests.RequestException as exc:
            logger.error("function_id=%s connection error: %s", function_id, exc)
            raise RuntimeApiError("Error connecting to the Runtime API", retryable=True) from exc

        if response.status_code in (200, 202):
            return
        retryable = response.status_code >= 500 or response.status_code in _RETRYABLE_CLIENT_ERRORS
        logger.warning(
            "function_id=%s unexpected status %s retryable=%s body=%s",
            function_id,
            response.status_code,
            retryable,
            response.text[:300],
        )
        raise RuntimeApiError(
            f"Unexpected status {response.status_code} for function {function_id}",
            retryable=retryable,
            status_code=response.status_code,
        )
