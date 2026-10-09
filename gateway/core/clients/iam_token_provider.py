"""IAM token for a service credential: exchanges an API key for a bearer token and keeps it fresh.

It is built from outside and handed to the clients that need a token (``FunctionsOperatorClient``), so the login
is explicit and can be shared or replaced. Build one per process and keep it: the token and its expiry are cached
inside the instance, so a new one per request would ask IAM for a new token every time.

Errors use the same two types as the clients: ``RuntimeApiError`` when the key itself is the problem (empty, malformed
or rejected by IAM, so asking again cannot help) and ``RuntimeApiRetryableError`` for anything else (IAM down, slow, or
answering garbage). The key and the token are never logged.
"""

import logging

from ibm_cloud_sdk_core import ApiException
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator

from core.clients.runtime_api_errors import RuntimeApiError, RuntimeApiRetryableError

logger = logging.getLogger("core.IamTokenProvider")

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

    def get_token(self) -> str:
        """A valid token. The SDK caches it, refreshes it near expiry and lets one thread at a time ask IAM while the
        others wait, so ask on every use and do not add a lock around it."""
        try:
            return self._authenticator.token_manager.get_token()
        except ApiException as exc:
            self._forget_failed_request()
            if exc.status_code in _KEY_REJECTED:
                logger.error("IAM rejected the API key with status %s", exc.status_code)
                raise RuntimeApiError(f"IAM rejected the API key (status {exc.status_code})") from exc
            logger.error("Could not get an IAM token, status %s", exc.status_code)
            raise RuntimeApiRetryableError("Could not get an IAM token") from exc
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._forget_failed_request()
            logger.error("Could not get an IAM token: %s", type(exc).__name__)
            raise RuntimeApiRetryableError("Could not get an IAM token") from exc

    def _forget_failed_request(self) -> None:
        """The token manager marks a request as active while it asks IAM and only clears the mark after a success. After
        a failure every later call would then sleep for up to 60 s waiting for a request that is already over. Clear
        the mark so the next call asks IAM again."""
        self._authenticator.token_manager.request_time = 0
