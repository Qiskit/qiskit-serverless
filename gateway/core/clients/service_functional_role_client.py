"""Client for the calls to the Runtime API made with the service credential that holds the functions operator role.

Today it sends the stored workload payload with ``PUT /functions/{function_id}``, which mirrors Functions jobs to the
Runtime API as workloads while ``workloads.mirror.enabled`` is on. Other calls made with that same credential belong
here too.

The pieces shared with other Runtime API clients live elsewhere: the errors in ``runtime_api_errors.py`` and the
regional host in ``core/domain/crn.py`` (``regional_base_url``).

One attempt per call and no internal retry: the caller decides what a failure means, and the type of the
``RuntimeApiRetryableError`` says trying again can help, a plain ``RuntimeApiError`` says it cannot.
"""

import logging
import threading

import requests
from django.conf import settings
from ibm_cloud_sdk_core import ApiException
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator

from core.clients.runtime_api_errors import RuntimeApiError, RuntimeApiRetryableError
from core.config_key import ConfigKey
from core.domain.crn import regional_base_url
from core.models import Config

logger = logging.getLogger("gateway.clients.service_functional_role")

_TRANSIENT_CLIENT_ERRORS = {408, 429}
_KEY_REJECTED = {400, 401, 403}
_DEFAULT_TIMEOUT_MS = 3000


class ServiceFunctionalRoleClient:
    """Sends the envelope built by ``core.domain.workload_payload.build_workload_payload``.

    Create one instance per process and keep it: each instance has its own IAM token manager and cache, so building
    one per request would ask IAM for a new token every time."""

    def __init__(self) -> None:
        self._authenticator: IAMAuthenticator | None = None
        self._authenticator_lock = threading.Lock()

    @staticmethod
    def _build_authenticator() -> IAMAuthenticator:
        try:
            return IAMAuthenticator(settings.FUNCTIONS_OPERATOR_API_KEY, url=settings.IAM_IBM_CLOUD_BASE_URL)
        except ValueError as exc:  # the SDK raises ValueError only from this constructor
            logger.error("FUNCTIONS_OPERATOR_API_KEY was rejected by the IAM client: %s", type(exc).__name__)
            raise RuntimeApiError("FUNCTIONS_OPERATOR_API_KEY is malformed") from exc

    def _token(self, timeout: float) -> str:
        """A valid IAM token. The SDK's token manager caches it and refreshes it near expiry, so ask on every call.
        Raises RuntimeApiError when the key itself is the problem and RuntimeApiRetryableError otherwise."""
        if self._authenticator is None:
            with self._authenticator_lock:
                if self._authenticator is None:
                    self._authenticator = self._build_authenticator()
        # The token manager waits 60 s by default, far above the budget of one mirror call. The timeout is dynamic
        # config, so set it on every call.
        self._authenticator.token_manager.http_config = {"timeout": timeout}
        try:
            return self._authenticator.token_manager.get_token()
        except ApiException as exc:
            if exc.status_code in _KEY_REJECTED:
                logger.error("IAM rejected FUNCTIONS_OPERATOR_API_KEY with status %s", exc.status_code)
                raise RuntimeApiError(f"IAM rejected FUNCTIONS_OPERATOR_API_KEY (status {exc.status_code})") from exc
            logger.error("Could not get an IAM token, status %s", exc.status_code)
            raise RuntimeApiRetryableError("Could not get an IAM token") from exc
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Could not get an IAM token: %s", type(exc).__name__)
            raise RuntimeApiRetryableError("Could not get an IAM token") from exc

    def put_function(self, payload: dict) -> None:
        """Send ``payload`` to the Runtime API. Returns when it applied it (200) or ignored it because the function was
        already terminal (202). Does nothing at all while ``workloads.mirror.enabled`` is off. Raises
        RuntimeApiError for a permanent failure (including FUNCTIONS_OPERATOR_API_KEY empty while it is on) and
        RuntimeApiRetryableError for a transient one."""
        if not Config.get_bool(ConfigKey.WORKLOADS_MIRROR_ENABLED):
            return
        if not settings.FUNCTIONS_OPERATOR_API_KEY:
            raise RuntimeApiError("FUNCTIONS_OPERATOR_API_KEY is not set")

        function_id, body = payload["function_id"], payload["body"]
        base_url = regional_base_url(
            settings.RUNTIME_API_BASE_URL, body.get("crn"), settings.RUNTIME_API_DEFAULT_REGION
        )
        timeout_ms = Config.get_int(ConfigKey.WORKLOADS_MIRROR_TIMEOUT_MS, default=_DEFAULT_TIMEOUT_MS)
        if timeout_ms <= 0:
            logger.warning(
                "%s is %s, using %s", ConfigKey.WORKLOADS_MIRROR_TIMEOUT_MS.value, timeout_ms, _DEFAULT_TIMEOUT_MS
            )
            timeout_ms = _DEFAULT_TIMEOUT_MS
        timeout = timeout_ms / 1000
        token = self._token(timeout)

        try:
            response = requests.put(
                f"{base_url}/api/v1/functions/{function_id}",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
                timeout=timeout,
            )
        except requests.RequestException as exc:
            logger.error("function_id=%s connection error: %s", function_id, exc)
            raise RuntimeApiRetryableError("Error connecting to the Runtime API") from exc

        if response.status_code in (200, 202):
            return
        transient = response.status_code >= 500 or response.status_code in _TRANSIENT_CLIENT_ERRORS
        logger.warning(
            "function_id=%s unexpected status %s transient=%s body=%s",
            function_id,
            response.status_code,
            transient,
            response.text[:300],
        )
        error_class = RuntimeApiRetryableError if transient else RuntimeApiError
        raise error_class(
            f"Unexpected status {response.status_code} for function {function_id}", status_code=response.status_code
        )
