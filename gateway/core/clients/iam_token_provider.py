"""IAM token for a service credential: exchanges an API key for a bearer token and keeps it fresh.

It is built from outside and handed to the clients that need a token (``FunctionsOperatorClient``), so the login
is explicit and can be shared or replaced. Build one per process and keep it: the token and its expiry are cached
inside the instance, so a new one per request would ask IAM for a new token every time.

Errors use the same two types as the clients: ``RuntimeApiError`` when the key itself is the problem (empty, malformed
or rejected by IAM, so asking again cannot help) and ``RetryableError`` for anything else (IAM down, slow, or
answering garbage). The key and the token are never logged.

A daemon thread renews the token in the background, so callers still just call ``get_token()`` and none of them waits
for a renewal. It starts after the first token, once per provider and per process, and renews when the token has less
than ``max(40% of its lifetime, 10 minutes)`` left. If IAM fails it tries again every 30 seconds and never ends. The
refresh that the SDK does at 80% of the lifetime inside ``get_token`` stays as a fallback.
"""

import logging
import os
import threading
import time
from functools import lru_cache
from typing import Callable, Optional

from ibm_cloud_sdk_core import ApiException
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator

from core.clients.runtime_api_errors import RuntimeApiError
from core.domain.exceptions.retryable_error import RetryableError
from core.external_call_metrics import IAM_TOKEN, observe_operation

logger = logging.getLogger("core.IamTokenProvider")

_KEY_REJECTED = {400, 401, 403}
_DEFAULT_TIMEOUT = (3, 5)  # seconds, (connect, read)

REFRESH_MIN_SECONDS = 600
REFRESH_FRACTION = 0.4
RETRY_SECONDS = 30


class IamTokenProvider:  # pylint: disable=too-many-instance-attributes
    """Gives a valid IAM token for ``api_key``. Safe to share between threads."""

    def __init__(
        self,
        api_key: str,
        iam_url: str,
        timeout: float | tuple[float, float] = _DEFAULT_TIMEOUT,
        clock: Callable[[], float] = time.time,
        wait: Optional[Callable[[float], bool]] = None,
    ) -> None:
        """``timeout`` (seconds, greater than zero) bounds the request to IAM; the SDK waits 60 s by default. It is
        a number or a ``(connect, read)`` pair, as in ``requests``. It is fixed here and not per call, because the
        token manager is shared by every thread that asks for a token.
        ``clock`` and ``wait`` are for tests: ``wait(seconds)`` sleeps and returns True when the refresher must stop.
        Raises RuntimeApiError if ``api_key`` is empty or malformed."""
        if not api_key:
            raise RuntimeApiError("The API key is not set")
        try:
            self._authenticator = IAMAuthenticator(api_key, url=iam_url)
        except ValueError as exc:  # the SDK raises ValueError only from this constructor
            logger.error("The API key was rejected by the IAM client: %s", type(exc).__name__)
            raise RuntimeApiError("The API key is malformed") from exc
        self._authenticator.token_manager.http_config = {"timeout": timeout}
        self._clock = clock
        self._wait = wait or self._wait_for_wake_or_stop
        self._wake = threading.Event()
        self._stopped = False
        self._state_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._thread_pid: Optional[int] = None
        self._seen_token: Optional[str] = None
        self._ttl = 0.0

    def get_token(self) -> str:
        """A valid token. A background thread renews it before it gets close to expiry, and the SDK caches it and lets
        one thread at a time ask IAM if it has to (first call, or the thread could not renew), so ask on every use and
        do not add a lock around it."""
        try:
            token = self._fetch()
        except ApiException as exc:
            self._forget_failed_request()
            if exc.status_code in _KEY_REJECTED:
                logger.error("IAM rejected the API key with status %s", exc.status_code)
                raise RuntimeApiError(f"IAM rejected the API key (status {exc.status_code})") from exc
            logger.warning("Could not get an IAM token, status %s", exc.status_code)
            raise RetryableError("Could not get an IAM token") from exc
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._forget_failed_request()
            logger.warning("Could not get an IAM token: %s", type(exc).__name__)
            raise RetryableError("Could not get an IAM token") from exc
        try:
            if self._record_token(token):
                self._ensure_refresher()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # The token is valid, so a refresher that cannot start must not fail the caller (the SDK refresh remains).
            logger.warning("Could not start the IAM token refresher: %s", type(exc).__name__)
        return token

    def _fetch(self) -> str:
        """Ask the SDK for the token and time the call. Used by callers and by the refresher, so every request to IAM
        is in the histogram."""
        token_manager = self._authenticator.token_manager
        # The SDK answers from its cache nearly every time, which would fill the histogram with zeros and hide the
        # few real requests. It asks IAM only when the token is expired or due for a refresh, so only then is it timed.
        # (Both checks are private to the SDK; a refresher renewing in between only costs one wrong sample.)
        # pylint: disable=protected-access
        if token_manager._is_token_expired() or token_manager._token_needs_refresh():
            with observe_operation(IAM_TOKEN):
                return token_manager.get_token()
        return token_manager.get_token()

    def invalidate(self, token: str) -> None:
        """Drop ``token`` from the cache, so the next ``get_token`` asks IAM for a new one. Use it when the API rejects
        a token (401): the SDK would otherwise keep giving the same one until it is near expiry. It only acts if
        ``token`` is still the cached one, so a late caller cannot discard the fresh token another thread just got."""
        token_manager = self._authenticator.token_manager
        with token_manager.lock:  # the check and the write are one step, or a token renewed in between would be dropped
            if token_manager.access_token != token:
                return
            token_manager.expire_time = 0
        self._wake.set()  # the refresher renews now instead of sleeping until the old deadline

    def close(self) -> None:
        """Stop the refresher thread. The provider still works, but the token is no longer renewed in the background."""
        self._stopped = True
        self._wake.set()

    def _record_token(self, token: str) -> bool:
        """Measure the lifetime of a token the first time it is seen (``expire_time`` minus now, never assumed). False
        if the expiry is unknown, so there is nothing to schedule."""
        expire_time = self._authenticator.token_manager.expire_time
        if not isinstance(expire_time, (int, float)) or expire_time <= 0:
            return False
        if token != self._seen_token:
            with self._state_lock:
                self._seen_token = token
                self._ttl = max(expire_time - self._clock(), 0.0)
        return True

    def _refresher_alive(self) -> bool:
        thread = self._thread
        return thread is not None and self._thread_pid == os.getpid() and thread.is_alive()

    def _ensure_refresher(self) -> None:
        """Start the refresher if this process has none. A forked child inherits the provider but not its thread."""
        if self._refresher_alive():
            return
        with self._state_lock:
            if self._stopped or self._refresher_alive():
                return
            if self._thread_pid not in (None, os.getpid()):
                self._wake = threading.Event()  # a forked child must not share the parent's event state
            self._thread = threading.Thread(target=self._refresh_loop, name="iam-token-refresher", daemon=True)
            self._thread_pid = os.getpid()
            self._thread.start()

    def _refresh_deadline(self) -> float:
        """Epoch seconds at which the token must be renewed: when less than ``max(40% of its lifetime, 10 minutes)``
        is left, but never earlier than half of its lifetime, or a token that lives 10 minutes or less would be renewed
        in a loop. A token without expiry (dropped by ``invalidate``) is due now."""
        expire_time = self._authenticator.token_manager.expire_time
        if expire_time <= 0:
            return self._clock()
        return expire_time - min(max(REFRESH_FRACTION * self._ttl, REFRESH_MIN_SECONDS), self._ttl / 2)

    def _wait_for_wake_or_stop(self, seconds: float) -> bool:
        """Sleep up to ``seconds``, or less if ``invalidate`` or ``close`` wakes the thread. True means stop."""
        self._wake.wait(seconds)
        self._wake.clear()
        return self._stopped

    def _refresh_loop(self) -> None:
        """Thread body: sleep until the deadline, renew, repeat. A failure is retried every 30 s, and the loop only ends
        when asked to stop."""
        token_manager = self._authenticator.token_manager
        min_wait = 0  # after a renewal, so a token that is already expired when it arrives cannot make a tight loop
        while True:
            if self._wait(max(self._refresh_deadline() - self._clock(), min_wait)):
                return
            if self._clock() < self._refresh_deadline():
                continue  # woken early, or the token was renewed by someone else meanwhile
            while True:
                try:
                    token_manager.refresh_time = 0  # make the SDK renew even though its own 80% mark is not reached
                    self._record_token(self._fetch())
                    min_wait = RETRY_SECONDS
                    break
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    self._forget_failed_request()
                    logger.warning("Could not renew the IAM token in the background: %s", type(exc).__name__)
                    if self._wait(RETRY_SECONDS):
                        return

    def _forget_failed_request(self) -> None:
        """The token manager marks a request as active while it asks IAM and only clears the mark after a success. After
        a failure every later call would then sleep for up to 60 s waiting for a request that is already over. Clear
        the mark so the next call asks IAM again."""
        self._authenticator.token_manager.request_time = 0


# This is a singleton actually
@lru_cache(maxsize=8)
def get_iam_token_provider(api_key: str, iam_url: str) -> IamTokenProvider:
    """Singleton per credentials (a few are kept, because each one owns a refresher thread that an evicted provider
    would leave running): the provider for this ``api_key`` and ``iam_url``, built the first time it is asked
    for (``lru_cache`` is the lazy singleton). The SDK caches the token on the provider, so building one per call would
    fetch a token and throw that cache away. Nothing is cached when the key is rejected, so the next call tries again.
    """
    return IamTokenProvider(api_key, iam_url)
