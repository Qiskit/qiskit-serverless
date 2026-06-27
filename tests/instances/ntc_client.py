# pylint: disable=line-too-long
"""Client for configuring NTC accounts and service instances in acceptance tests.

This is a Python port of the bash workflow used to seed the permission tests. It talks to
two NTC hosts, each with a DIFFERENT authorization scheme, both derived from a single API key:

  - the account admin API (``quantum.test.cloud.ibm.com``) authenticates with
    ``Authorization: apikey <API_KEY>`` and configures account plan entitlements, and
  - the resource-controller (``resource-controller.test.cloud.ibm.com``) authenticates with
    ``Authorization: Bearer <BEARER>`` and configures instance entitlements. The bearer is
    obtained by exchanging the API key at the IAM token endpoint
    (``iam.test.cloud.ibm.com/identity/token``) and is cached for the life of the client.

All write methods use read-modify-write: they fetch the current document, replace only the
``functions`` / ``custom_functions`` keys, and send the rest back untouched, so existing fields
(plan_id, usage_*, backends, ...) are preserved.

Every HTTP access is logged (method, URL, auth scheme with the secret partially masked, a short
body summary and the response status) under the ``instances.ntc_client`` logger, so a test run
shows exactly which credentials and data were used against which endpoint.

NOTE: the exact request/response payload shapes are derived from the original bash script and the
NTC source. They must be validated against staging; adjust here if NTC's contract differs.
"""

import logging
import urllib.parse

import requests

logger = logging.getLogger("instances.ntc_client")

# Server-computed plan fields that must NOT be echoed back on the account PUT (cause HTTP 500).
_COMPUTED_PLAN_FIELDS = {"unallocated_usage_seconds"}

# Sentinel for the ``custom_permissions`` argument meaning "do not send custom_functions at all"
# (the server keeps its current value). This is distinct from None, which clears the field.
PRESERVE = object()


def _custom_functions_value(custom_permissions):
    """Map the ``custom_permissions`` argument to the ``custom_functions`` payload value.

    Three states (PRESERVE is handled by the callers, which omit the key entirely):
      - a non-empty list -> ``{"permissions": [...]}``  (set those permissions)
      - None or []        -> ``None``                    (clear; the whole custom_functions field
                              is set to null. Both an empty list AND ``{"permissions": null}`` are
                              rejected with HTTP 422 "custom_functions permissions must not be
                              empty", so the entire field must be nulled out instead.)
    """
    if not custom_permissions:  # None or []
        return None
    return {"permissions": list(custom_permissions)}


def _custom_log(custom_permissions):
    """Human-readable summary of the custom_permissions intent for logging."""
    if custom_permissions is PRESERVE:
        return "<preserve>"
    if not custom_permissions:  # None or []
        return "<clear>"
    return list(custom_permissions)


def mask_secret(value, show_start=6, show_end=4):
    """Return a partially masked secret, e.g. 'ONy8hh...iHih', safe to log."""
    if not value:
        return "<empty>"
    if len(value) <= show_start + show_end:
        return "*" * len(value)
    return f"{value[:show_start]}...{value[-show_end:]}"


def _mask_auth(headers):
    """Mask the credential inside an Authorization header for logging."""
    auth = headers.get("Authorization", "")
    scheme, _, secret = auth.partition(" ")
    if secret:
        return f"{scheme} {mask_secret(secret)}"
    return mask_secret(auth)


class NtcApiError(Exception):
    """Raised when an NTC endpoint returns a non-2xx response (or a plan is missing)."""

    def __init__(self, message, status=None, body=None):
        super().__init__(message)
        self.status = status
        self.body = body


def _check(response):
    """Raise NtcApiError if the response is not 2xx, otherwise return it."""
    if not 200 <= response.status_code < 300:
        logger.warning("NTC <- HTTP %s from %s: %s", response.status_code, response.url, response.text[:300])
        raise NtcApiError(
            f"NTC request to {response.url} failed with HTTP {response.status_code}",
            status=response.status_code,
            body=response.text,
        )
    logger.info("NTC <- HTTP %s from %s", response.status_code, response.url)
    return response


class NtcAdminClient:  # pylint: disable=too-many-instance-attributes
    """Configures account plans and instance entitlements in NTC.

    Authentication is derived from a single API key: the account admin API uses
    ``apikey <API_KEY>`` directly, while the resource-controller uses a ``Bearer`` token
    exchanged from the API key at the IAM token endpoint. ``subscription_name`` selects
    which account plan to mutate.
    """

    def __init__(  # pylint: disable=too-many-arguments, too-many-positional-arguments
        self,
        account_id,
        api_key,
        rc_api_key=None,
        admin_base="https://quantum.test.cloud.ibm.com",
        rc_base="https://resource-controller.test.cloud.ibm.com",
        iam_base="https://iam.test.cloud.ibm.com",
        subscription_name="flex",
        timeout=30,
    ):
        self.account_id = account_id
        # api_key: account admin API ("apikey" scheme).
        # rc_api_key: resource-controller (exchanged for an IAM Bearer). Falls back to api_key
        # when not provided, so single-credential setups keep working.
        self.api_key = api_key
        self.rc_api_key = rc_api_key or api_key
        self.admin_base = admin_base.rstrip("/")
        self.rc_base = rc_base.rstrip("/")
        self.iam_base = iam_base.rstrip("/")
        self.subscription_name = subscription_name
        self.timeout = timeout
        self._bearer = None
        logger.info(
            "NtcAdminClient configured: account_id=%s account_api_key=%s rc_api_key=%s admin_base=%s rc_base=%s iam_base=%s subscription_name=%s",
            account_id,
            mask_secret(self.api_key),
            mask_secret(self.rc_api_key),
            self.admin_base,
            self.rc_base,
            self.iam_base,
            subscription_name,
        )

    # --- IAM token exchange ------------------------------------------------------------------

    def _iam_bearer(self):
        """Exchange the API key for an IAM bearer token (cached for the client's lifetime)."""
        if self._bearer is None:
            url = f"{self.iam_base}/identity/token"
            logger.info(
                "NTC -> POST %s (IAM token exchange, resource-controller key) apikey=%s",
                url,
                mask_secret(self.rc_api_key),
            )
            response = _check(
                requests.post(
                    url,
                    params={
                        "apikey": self.rc_api_key,
                        "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                    },
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "application/json",
                    },
                    timeout=self.timeout,
                )
            )
            self._bearer = response.json()["access_token"]
            logger.info("NTC IAM bearer obtained: %s", mask_secret(self._bearer))
        return self._bearer

    # --- account (account plans = maximum limit) ---------------------------------------------

    def _account_url(self):
        return f"{self.admin_base}/api/v1/accounts/{self.account_id}"

    def _account_headers(self):
        # The account admin API authenticates with the API key directly ("apikey" scheme).
        return {"Authorization": f"apikey {self.api_key}", "Content-Type": "application/json"}

    def get_account(self):
        """Return the account configuration as parsed JSON."""
        headers = self._account_headers()
        logger.info("NTC -> GET %s (account) auth=%s", self._account_url(), _mask_auth(headers))
        response = _check(requests.get(self._account_url(), headers=headers, timeout=self.timeout))
        return response.json()

    def set_account_entitlements(self, functions, custom_permissions=PRESERVE):
        """Replace the ``functions`` (and optionally ``custom_functions``) of the configured plan.

        Read-modify-write: fetch the account, locate the plan whose ``subscription_name`` matches
        ``self.subscription_name`` (never create it), and PUT back ONLY that plan with its
        ``functions``/``custom_functions`` set.

        ``custom_permissions`` is three-state: a non-empty list sets the permissions, ``None`` (or
        ``[]``) clears them by nulling the whole ``custom_functions`` field (both an empty list and
        ``{"permissions": null}`` return HTTP 422), and the default ``PRESERVE`` leaves the plan's
        ``custom_functions`` untouched.

        Note: the replace endpoint upserts per plan, so sending only the target plan preserves the
        others. Sending the whole plan list (round-trip) makes the server return HTTP 500, and the
        server-computed fields (e.g. ``unallocated_usage_seconds``) must be stripped from the plan.
        Raises NtcApiError if the plan is not present.
        """
        account = self.get_account()
        plans = account.get("plans") or []
        target = None
        for plan in plans:
            if plan.get("subscription_name") == self.subscription_name:
                target = plan
                break
        if target is None:
            raise NtcApiError(f"plan '{self.subscription_name}' not found in account")

        plan_payload = {k: v for k, v in target.items() if k not in _COMPUTED_PLAN_FIELDS}
        plan_payload["functions"] = functions
        if custom_permissions is not PRESERVE:
            plan_payload["custom_functions"] = _custom_functions_value(custom_permissions)

        body = {
            "account_id": account.get("account_id") or f"a/{self.account_id}",
            "plans": [plan_payload],
        }
        headers = self._account_headers()
        logger.info(
            "NTC -> PUT %s (account) auth=%s plan=%s functions=%d custom_permissions=%s",
            self._account_url(),
            _mask_auth(headers),
            self.subscription_name,
            len(functions),
            _custom_log(custom_permissions),
        )
        _check(
            requests.put(
                self._account_url(),
                headers=headers,
                json=body,
                timeout=self.timeout,
            )
        )

    # --- instance (entitlements) -------------------------------------------------------------

    def _instance_url(self, crn):
        encoded = urllib.parse.quote(crn, safe="")
        return f"{self.rc_base}/v2/resource_instances/{encoded}"

    def _instance_headers(self):
        # The resource-controller uses a Bearer token exchanged from the API key via IAM.
        return {"Authorization": f"Bearer {self._iam_bearer()}", "Content-Type": "application/json"}

    def get_instance(self, crn):
        """Return the service instance document as parsed JSON."""
        headers = self._instance_headers()
        logger.info("NTC -> GET %s (instance) auth=%s crn=%s", self._instance_url(crn), _mask_auth(headers), crn)
        response = _check(requests.get(self._instance_url(crn), headers=headers, timeout=self.timeout))
        return response.json()

    def set_instance_entitlements(self, crn, functions, custom_permissions=PRESERVE):
        """Replace the instance ``functions`` (and optionally ``custom_functions``).

        Read-modify-write over ``parameters``: other parameters (backends, usage, ...) are kept.
        ``custom_permissions`` is three-state: a non-empty list sets the permissions, ``None`` (or
        ``[]``) clears them by nulling the whole ``custom_functions`` field (both an empty list and
        ``{"permissions": null}`` return HTTP 422), and the default ``PRESERVE`` leaves the instance
        ``custom_functions`` untouched.
        """
        instance = self.get_instance(crn)
        params = instance.get("parameters") or {}
        params["functions"] = functions
        if custom_permissions is not PRESERVE:
            params["custom_functions"] = _custom_functions_value(custom_permissions)
        headers = self._instance_headers()
        logger.info(
            "NTC -> PATCH %s (instance) auth=%s crn=%s functions=%d custom_permissions=%s",
            self._instance_url(crn),
            _mask_auth(headers),
            crn,
            len(functions),
            _custom_log(custom_permissions),
        )
        _check(
            requests.patch(
                self._instance_url(crn),
                headers=headers,
                json={"parameters": params},
                timeout=self.timeout,
            )
        )
