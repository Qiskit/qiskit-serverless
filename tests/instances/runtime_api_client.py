# pylint: disable=import-error, line-too-long
"""Read-only client for the Runtime API ``/functions`` endpoint (the gateway's ground truth).

When the serverless client calls the gateway, the gateway authenticates the request and asks the
Runtime API which functions the caller's instance is entitled to. That call is (see
``gateway/api/clients/function_access_client.py``)::

    GET {RUNTIME_API_BASE_URL}/api/v1/functions
    Headers:  Service-CRN: <crn>   Authorization: apikey <user_token>

with the SAME token the user presented to the gateway (for channel ``ibm_quantum_platform`` that is
the IBM Cloud API key, i.e. our ``GATEWAY_TOKEN``). A 204 means "instance not configured" and makes
the gateway fall back to legacy Django authorization.

This client reproduces that exact call so the tests can observe the ground truth directly, BEFORE
the gateway's per-CRN cache. That makes propagation waits authoritative (we poll the real source of
truth instead of sleeping) and lets the tests assert that NTC actually stored what we asked for.
"""

import logging

import requests

from instances.ntc_client import mask_secret

logger = logging.getLogger("instances.runtime_api_client")


class RuntimeFunctions:
    """Parsed result of a Runtime API ``/functions`` read.

    Mirrors what the gateway computes from the same response:
      - ``not_configured``: the endpoint returned 204 (gateway falls back to legacy authorization).
      - ``functions``: list of ``{"provider", "name", "permissions" (set), "business_model"}``.
      - ``custom_permissions``: set of custom function permissions.
    """

    def __init__(self, status_code, functions, custom_permissions):
        self.status_code = status_code
        self.not_configured = status_code == 204
        self.functions = functions
        self.custom_permissions = custom_permissions

    def entry(self, provider, name):
        """Return the entitlement entry for ``provider/name`` (or None)."""
        for fn in self.functions:
            if fn["provider"] == provider and fn["name"] == name:
                return fn
        return None

    def has_function(self, provider, name):
        """Whether ``provider/name`` is present in the entitlements."""
        return self.entry(provider, name) is not None

    def permissions(self, provider, name):
        """Permissions granted to ``provider/name`` (empty set if absent)."""
        entry = self.entry(provider, name)
        return set(entry["permissions"]) if entry else set()

    def summary(self):
        """Compact, log-friendly description of the entitlements."""
        if self.not_configured:
            return "204 not-configured (legacy fallback)"
        fns = ", ".join(f"{f['provider']}/{f['name']}({len(f['permissions'])}p)" for f in self.functions)
        return f"{self.status_code} functions=[{fns}] custom={sorted(self.custom_permissions)}"


class RuntimeApiError(Exception):
    """Raised when the Runtime API returns an unexpected (non 200/204) status."""

    def __init__(self, message, status=None, body=None):
        super().__init__(message)
        self.status = status
        self.body = body


class RuntimeApiClient:  # pylint: disable=too-few-public-methods
    """Reproduces the gateway's Runtime API ``/functions`` read for a given instance CRN."""

    def __init__(self, base_url, api_key, timeout=30):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self, crn):
        # Same headers the gateway sends: the instance CRN and the user's token as "apikey".
        return {"Service-CRN": crn, "Authorization": f"apikey {self.api_key}"}

    def get_functions(self, crn):
        """Read the entitlements the Runtime API exposes for ``crn`` (the gateway's ground truth).

        Returns a RuntimeFunctions (including the 204 "not configured" case). Raises RuntimeApiError
        for any other non-200 status.
        """
        url = f"{self.base_url}/api/v1/functions"
        logger.info(
            "RuntimeAPI -> GET %s | headers: Service-CRN=%s, Authorization=apikey %s",
            url,
            crn,
            mask_secret(self.api_key),
        )
        response = requests.get(url, headers=self._headers(crn), timeout=self.timeout)

        if response.status_code == 204:
            logger.info(
                "RuntimeAPI <- HTTP 204 (instance not configured) for crn=%s body=%s", crn, response.text or "<empty>"
            )
            return RuntimeFunctions(status_code=204, functions=[], custom_permissions=set())

        if response.status_code != 200:
            logger.warning("RuntimeAPI <- HTTP %s from %s: %s", response.status_code, url, response.text[:500])
            raise RuntimeApiError(
                f"Runtime API GET {url} returned HTTP {response.status_code}",
                status=response.status_code,
                body=response.text,
            )

        payload = response.json()
        functions = []
        for entry in payload.get("functions", []) or []:
            functions.append(
                {
                    "provider": entry.get("provider"),
                    "name": entry.get("name"),
                    "permissions": set(entry.get("permissions", []) or []),
                    "business_model": entry.get("business_model"),
                }
            )
        custom_permissions = set((payload.get("custom_functions") or {}).get("permissions", []) or [])
        result = RuntimeFunctions(status_code=200, functions=functions, custom_permissions=custom_permissions)
        logger.info("RuntimeAPI parsed for crn=%s: %s", crn, result.summary())
        return result
