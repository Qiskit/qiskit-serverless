"""IAM token for a service credential: exchanges an API key for a bearer token and keeps it fresh.

It is built from outside and handed to the clients that need a token (``ServiceFunctionalRoleClient``), so the login
is explicit and can be shared or replaced. Build one per process and keep it: the token and its expiry are cached
inside the instance, so a new one per request would ask IAM for a new token every time.

Errors use the same two types as the clients: ``RuntimeApiError`` when the key itself is the problem (empty, malformed
or rejected by IAM, so asking again cannot help) and ``RuntimeApiRetryableError`` for anything else (IAM down, slow, or
answering garbage). The key and the token are never logged.
"""

import logging
import threading

from ibm_cloud_sdk_core import ApiException
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator

from core.clients.runtime_api_errors import RuntimeApiError, RuntimeApiRetryableError

logger = logging.getLogger("gateway.clients.iam_token_provider")

_KEY_REJECTED = {400, 401, 403}
_DEFAULT_TIMEOUT = 3  # seconds


class IamTokenProvider:
    """Gives a valid IAM token for ``api_key``. Safe to share between threads."""

    def __init__(self, api_key: str, iam_url: str, timeout: float = _DEFAULT_TIMEOUT) -> None:
        """``timeout`` (seconds, greater than zero) bounds the request to IAM; the SDK waits 60 s by default. It is
        fixed here and not per call, because the token manager is shared by every thread that asks for a token.
        Raises RuntimeApiError if ``api_key`` is empty or malformed."""
        if not api_key:
            raise RuntimeApiError("The API key is not set")
        try:
            self._authenticator = IAMAuthenticator(api_key, url=iam_url)
        except ValueError as exc:  # the SDK raises ValueError only from this constructor
            logger.error("The API key was rejected by the IAM client: %s", type(exc).__name__)
            raise RuntimeApiError("The API key is malformed") from exc
        self._authenticator.token_manager.http_config = {"timeout": timeout}
        self._lock = threading.Lock()

    def get_token(self) -> str:
        """A valid token. The SDK caches it and refreshes it near expiry, so ask on every use. The lock makes the
        threads that find it expired wait for one refresh instead of each sending their own."""
        with self._lock:
            try:
                return self._authenticator.token_manager.get_token()
            except ApiException as exc:
                if exc.status_code in _KEY_REJECTED:
                    logger.error("IAM rejected the API key with status %s", exc.status_code)
                    raise RuntimeApiError(f"IAM rejected the API key (status {exc.status_code})") from exc
                logger.error("Could not get an IAM token, status %s", exc.status_code)
                raise RuntimeApiRetryableError("Could not get an IAM token") from exc
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error("Could not get an IAM token: %s", type(exc).__name__)
                raise RuntimeApiRetryableError("Could not get an IAM token") from exc
