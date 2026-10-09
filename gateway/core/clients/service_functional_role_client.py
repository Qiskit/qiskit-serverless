"""Client for the calls to the Runtime API made with the service credential that holds the functions operator role.

Today it sends a workload with ``PUT /functions/{function_id}``, which mirrors Functions jobs to the Runtime API.
Other calls made with that same credential belong here too.

The client does not log in: it is given an ``IamTokenProvider`` (``iam_token_provider.py``) built by the caller from
the service key, for example ``IamTokenProvider(settings.FUNCTIONS_OPERATOR_API_KEY, settings.IAM_IBM_CLOUD_BASE_URL)``.
The other pieces shared with other Runtime API clients live elsewhere too: the errors in ``runtime_api_errors.py`` and
the regional host in ``core/domain/crn.py`` (``regional_base_url``).

One attempt per call and no internal retry: the caller decides what a failure means, and the type of the
``RuntimeApiRetryableError`` says trying again can help, a plain ``RuntimeApiError`` says it cannot.
"""

import logging

import requests
from django.conf import settings

from core.clients.iam_token_provider import IamTokenProvider
from core.clients.runtime_api_errors import RuntimeApiError, RuntimeApiRetryableError
from core.domain.crn import regional_base_url

logger = logging.getLogger("gateway.clients.service_functional_role")

_TRANSIENT_CLIENT_ERRORS = {408, 429}
_DEFAULT_TIMEOUT = 3  # seconds


class ServiceFunctionalRoleClient:
    """Sends the ``function_id`` and ``body`` of the envelope built by
    ``core.domain.workload_payload.build_workload_payload``. It holds no state besides the token provider, so one
    instance can be shared by every thread of the process."""

    def __init__(self, token_provider: IamTokenProvider) -> None:
        self._token_provider = token_provider

    def put_function(self, function_id: str, body: dict, timeout: float = _DEFAULT_TIMEOUT) -> None:
        """Replace the function ``function_id`` on the Runtime API with ``body``. Returns when it applied it (200) or
        ignored it because the function was already terminal (202). ``timeout`` is in seconds, greater than zero, and
        bounds the PUT; the request for the token has the timeout of the token provider. Raises RuntimeApiError for a
        permanent failure and RuntimeApiRetryableError for a transient one, token errors included."""
        base_url = regional_base_url(
            settings.RUNTIME_API_BASE_URL, body.get("crn"), settings.RUNTIME_API_DEFAULT_REGION
        )
        token = self._token_provider.get_token()

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
