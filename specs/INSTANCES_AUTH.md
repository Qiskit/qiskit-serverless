# Instance-based authorization

This document describes the instance-based authorization system, which grants granular per-function permissions to users based on their IBM Quantum platform instance (CRN).

## Overview

The authorization system supports two modes that coexist:

1. **Legacy Django groups**: the original system, where users are granted access to provider functions through Django group membership. Access is at the provider level (either you belong to an admin group or you don't).
2. **Runtime instances (external client)**: a new system where an external service (`FunctionAccessClient`) determines, given a user's CRN, exactly which functions they can access and with which specific actions. Access is at the function level.

The two systems operate as a **dual with fallback**: the external client is consulted first, and if it does not respond (or no CRN is present), the system falls back to Django groups without any change in behavior.

```
request.auth.instance (CRN)
        |
        v
FunctionAccessClient.get_accessible_functions(crn)
        |
        |-- has_response=True  --> use external client results (instance-based authorization)
        |
        +-- has_response=False --> use Django groups (legacy, unchanged behavior)
```

## When the external client is consulted

The external client is called **once per request**, in the authentication middleware (`CustomTokenBackend`). The result is stored in `request.auth.accessible_functions` and reused by all views and use cases in that request.

The client is only relevant when the user is **not the owner** of the function. If the user is the author of a function (whether serverless or provider), they have full access without consulting the client. This is consistent with the existing behavior.

## Platform permissions

When the external client responds, it returns for each accessible function a set of actions (platform permissions) that the user's instance is allowed to perform. These are dot-notation strings grouped by domain:

| Constant                                | Value                           | Scope    | Endpoints                                                          |
|-----------------------------------------|---------------------------------|----------|--------------------------------------------------------------------|
| `PLATFORM_PERMISSION_READ`              | `function.read`                 | User     | Function list (catalog/all), get by title                          |
| `PLATFORM_PERMISSION_RUN`               | `function.run`                  | User     | Run function                                                       |
| `PLATFORM_PERMISSION_USER_FILES_READ`   | `function-files.read`           | User     | `v1/files/` list, download                                         |
| `PLATFORM_PERMISSION_USER_FILES_WRITE`  | `function-files.write`          | User     | `v1/files/` upload, delete                                         |
| `PLATFORM_PERMISSION_PROVIDER_UPLOAD`   | `function.write`                | Provider | Upload provider function                                           |
| `PLATFORM_PERMISSION_JOBS_READ`         | `function-job.read`             | Provider | `v1/jobs/provider`, `v1/jobs/<id>` (retrieve, non-author)          |
| `PLATFORM_PERMISSION_PROVIDER_LOGS`     | `function-provider-logs.read`   | Provider | `v1/jobs/<id>/provider-logs`                                       |
| `PLATFORM_PERMISSION_PROVIDER_FILES_READ`  | `function-provider-files.read`  | Provider | `v1/files/provider/` list, download                             |
| `PLATFORM_PERMISSION_PROVIDER_FILES_WRITE` | `function-provider-files.write` | Provider | `v1/files/provider/` upload, delete                             |

## Core data structures

### `FunctionAccessEntry`

Represents a single function that the user's instance can access. Contains:
- `provider_name`: the provider that owns the function
- `function_title`: the function's title
- `permissions`: the set of allowed actions (`PLATFORM_PERMISSION_*` strings)
- `business_model`: how jobs will be billed when the function is run (`TRIAL`, `SUBSIDIZED`, or `CONSUMPTION`)

The `business_model` field is validated against the allowed values at construction time. It is only meaningful when `PLATFORM_PERMISSION_RUN` is present in `permissions`.

### `FunctionAccessResult`

The aggregate response from the client for a given CRN. Contains:
- `use_legacy_authorization`: `True` when the client did not respond (fallback to Django groups), `False` when the client responded.
- `functions`: the list of `FunctionAccessEntry` objects (empty when `use_legacy_authorization=True`).

Helper methods:
- `get_function(provider_name, function_title)`: returns the entry matching that function, or `None`.
- `has_permission_for_function(provider_name, function_title, permission)`: returns `True` if the function exists and has the given permission.
- `has_permission_for_provider(provider_name, permission)`: returns `True` if any function of that provider has the given permission.
- `get_functions_by_provider(permission)`: returns a `{provider_name: {function_title, ...}}` dict with all functions that have the given permission.

## Authorization flow per endpoint

### Endpoints that do not need the client

These endpoints only allow the job's author. There is no provider role or external user, so no client lookup is needed:

| Endpoint                    | Reason                                              |
|-----------------------------|-----------------------------------------------------|
| `v1/jobs/` (list)           | Filters by `author=user` in the queryset            |
| `v1/jobs/<id>/logs`         | Author only                                         |
| `v1/jobs/<id>/result`       | Author only                                         |
| `v1/jobs/<id>/stop`         | Author only                                         |
| `v1/jobs/<id>/sub_status`   | Author only                                         |
| `v1/jobs/<id>/event`        | Author only                                         |
| `v1/jobs/<id>/events`       | Author only                                         |
| `v1/jobs/<id>/runtime_jobs` | Author only                                         |
| `programs/list` (serverless)| Only the user's own functions (`author=user, provider=None`) |

### Provider access checks

For provider-related operations, the `ProviderAccessPolicy` class exposes named methods per operation. Each method internally selects the appropriate platform permission:

| Method                  | Platform permission used                   | Authorization when legacy    |
|-------------------------|--------------------------------------------|------------------------------|
| `can_upload_function`   | `PLATFORM_PERMISSION_PROVIDER_UPLOAD`      | `admin_groups` intersection  |
| `can_list_jobs`         | `PLATFORM_PERMISSION_JOBS_READ`            | `admin_groups` intersection  |
| `can_retrieve_job`      | `PLATFORM_PERMISSION_JOBS_READ`            | `admin_groups` intersection  |
| `can_read_logs`         | `PLATFORM_PERMISSION_PROVIDER_LOGS`        | `admin_groups` intersection  |
| `can_read_files`        | `PLATFORM_PERMISSION_PROVIDER_FILES_READ`  | `admin_groups` intersection  |
| `can_write_files`       | `PLATFORM_PERMISSION_PROVIDER_FILES_WRITE` | `admin_groups` intersection  |

When the external client responds, each of these checks operates at **function level**: having permission for function A does not imply permission for function B, even within the same provider. When using legacy Django groups, checks operate at **provider level** (belonging to an admin group grants access to all functions of that provider).

### Function list and queryset filtering

When listing provider functions (catalog), the system needs to filter the queryset to include only the functions the user is allowed to see. The `FunctionsQuerySet.with_permission()` method supports both authorization modes:

- **External client**: filters by the explicit list of `{provider_name: {function_titles}}` from `get_functions_by_provider(permission)`, combined with the user's own functions.
- **Legacy**: filters by Django group membership (unchanged).

If the external client responds but grants no functions, the user sees only their own functions (no special-case needed — the filter simply produces no provider matches).

### Run endpoint and `business_model`

When a user runs a provider function and the external client responds, the `business_model` for the resulting job is taken directly from the `FunctionAccessEntry` (instead of being derived from `is_trial()`). This ensures the billing model is determined by the platform instance configuration, not by local group membership.

When the client does not respond, the existing `is_trial()` logic is used unchanged.

## Design decisions

### Function-level vs. provider-level granularity

When the external client responds, authorization checks are performed at function level (`provider_name + function_title`). This is more precise than the legacy system, where belonging to an admin group grants blanket access to all functions of a provider. The external client may grant access to only a subset of a provider's functions, and the system respects that.

### Provider file access no longer requires run permission

In the legacy system, managing provider files required both admin group membership and `run_program` permission. This was a design flaw: `run_program` is a consumer permission (execute the function), not an admin permission. A provider admin should be able to manage files for any of their provider's functions without needing execution permission. In the new system, provider file access only requires admin access (`can_read_files` / `can_write_files`), independent of run permission.

### `PLATFORM_PERMISSION_JOBS_READ` unifies list and retrieve

A separate permission for retrieving individual jobs (`job.retrieve`) was considered but eliminated. If you have permission to list jobs for a function, it is consistent to also be able to read each individual job. Both `can_list_jobs` and `can_retrieve_job` use the same `PLATFORM_PERMISSION_JOBS_READ` constant.

### `accessible_functions` is mandatory at every integration point

The `accessible_functions` parameter is required (not optional) in all use cases and policy methods that need it. This prevents accidentally omitting it, which would silently fall back to legacy behavior in cases where the caller should have been using the external result.

## Acceptance tests: reconfigurable-instance suite

The `tests/instances/` suite exercises the instance-based authorization end to end against a real
staging deployment. Instead of standing up a fixed instance per permission level, it drives a
**single reconfigurable service instance** through the NTC APIs and reuses the same battery of
`/functions` assertions at every level (NONE / USER / PROVIDER / ALL). The relevant pieces:

- `instances/ntc_client.py` (`NtcAdminClient`): the generic HTTP client that mutates account plans
  and instance entitlements in NTC. It knows nothing about this suite (no CRN, no superset, no levels).
- `instances/instance_client.py` (`InstanceClient`): wraps `NtcAdminClient` with the two
  suite-specific facts the raw client lacks (the CRN under test and the account superset). Putting the
  instance into a level is two explicit writes at the call site: `reset_account_with_all_functions()`
  (widen the account to the superset so the broker accepts the grant) then
  `set_entitlements(functions, custom)` (PATCH the instance). `set_account_entitlements(functions,
  custom)` writes the account to an arbitrary set, which the propagation tests use to narrow it below
  the superset.
- `instances/runtime_api_client.py` (`RuntimeApiClient`): a read-only client for the Runtime API
  `/functions` endpoint, the same ground truth the gateway authorizes against.
- `instances/conftest.py`: the fixtures (including `instance`, an `InstanceClient`) and the
  per-level entitlement sets.
- `instances/test_instance_permissions.py`: the per-level test classes (NONE / USER / PROVIDER / ALL
  and the custom-function variant) that run the shared assertion battery.
- `instances/test_runtime_api.py`: asserts the Runtime API reflects each configured level exactly.
- `instances/test_instance_propagation.py`: black-box tests of the account -> instance sync.
- `instances/permission_checks.py`: the shared `/functions` assertions reused at every level.

The **staging tests** (everything that talks to NTC) are **skipped** unless `NTC_API_KEY`,
`NTC_ACCOUNT_ID` and `TEST_RECONFIG_INSTANCE` are set, so they are inert in CI without staging
credentials. The offline client tests (`test_ntc_client.py`, `test_runtime_api_client.py`) do not
use those credentials and run in every CI job.

### Two NTC endpoints, two authorization schemes

A single API key drives two different NTC hosts, each with its own auth header:

| Concern | Host | Auth header | What it configures |
|---------|------|-------------|--------------------|
| Account plan (the maximum grant) | `quantum.test.cloud.ibm.com` (account admin API) | `Authorization: apikey <API_KEY>` | The account plan entitlements (`functions`, `custom_functions`) per `subscription_name` (default `flex`). |
| Instance entitlements | `resource-controller.test.cloud.ibm.com` | `Authorization: Bearer <BEARER>` | The per-instance entitlements, stored under `parameters.functions` / `parameters.custom_functions` of the resource instance. |

The bearer is **not** the API key: it is obtained by exchanging the API key (`rc_api_key`, falling
back to `api_key`) at the IAM token endpoint (`iam.test.cloud.ibm.com/identity/token`, grant type
`urn:ibm:params:oauth:grant-type:apikey`) and cached for the life of the client. The split exists
because the instance may live in a different IBM Cloud account than the admin key, so the
resource-controller path can use a distinct credential (`NTC_RC_API_KEY`).

All write methods are **read-modify-write**: they GET the current document, replace only the
`functions` / `custom_functions` keys, and send the rest back untouched, so unrelated fields
(`plan_id`, `usage_limit_seconds`, `backends`, ...) are preserved. The instance PATCH additionally
stamps an advancing `timestamp` so the Runtime API re-syncs (see the Runtime API ground truth
section below).

### Account PUT peculiarities

The account `PUT` has two non-obvious requirements, both learned from staging:

1. **Send only the target plan, not the whole plan list.** The replace endpoint upserts per plan, so
   sending only the `flex` plan preserves the others. Echoing back the full plan list makes the
   server return **HTTP 500**.
2. **Strip server-computed fields.** Fields like `unallocated_usage_seconds` are computed by the
   server; echoing them back on the PUT also triggers an error, so they are removed before sending
   (`_COMPUTED_PLAN_FIELDS`).

### The three-state `custom_functions` contract

`custom_functions` (the holder of `function-custom.write` / `function-custom.run`) cannot be sent as
an empty collection. Both `custom_functions: []` **and** `custom_functions: {"permissions": null}`
are rejected with **HTTP 422 "custom_functions permissions must not be empty"**. To support
"clear it" without hitting that error, the client models three distinct intents through the
`custom_permissions` argument:

| Intent | Argument value | Payload sent | Meaning |
|--------|----------------|--------------|---------|
| Set | a non-empty list | `custom_functions: {"permissions": [...]}` | Grant exactly these custom permissions. |
| Clear | `None` or `[]` | `custom_functions: null` | Remove all custom permissions by nulling the **whole** field (not the inner list). |
| Preserve | omitted (default `PRESERVE` sentinel) | the key is not sent at all | Leave whatever the server currently has untouched. |

`PRESERVE` is a module-level sentinel object distinct from `None`, so "do not touch" and "clear"
never collapse into the same request. The instance PATCH follows the same contract over
`parameters.custom_functions`.

### Account -> instance sync is narrow-only

Saving the account runs a sync that NARROWS each instance's effective entitlements to the
intersection with the account, keyed by `(provider, name, business_model)`. The narrow is applied in
the Runtime API's effective view (it does **not** rewrite the resource-controller instance document),
and that propagation is **asynchronous**: it is not guaranteed to be visible on `/functions` the
instant the account save returns. It is critical to understand that this sync **only ever narrows; it
never re-adds**:

- Removing a function from the account removes it from every instance (asynchronously, see the cache
  section below).
- Re-adding it to the account does **not** restore it on the instance; the instance must be
  reconfigured directly via the resource-controller PATCH.
- The broker rejects an instance PATCH that asks for more than the account currently grants, so the
  account must hold a **superset** of every instance level before each instance change. This is why
  every test calls `reset_account_with_all_functions()` (widen the account to the superset) right
  before `set_entitlements` (PATCH the instance) — two explicit writes, in that order.

`GET /functions` returns the instance entitlements as-is, with no account intersection applied at
read time; the intersection only happens at account-save time.

### Empty instance (204) vs. configured-empty (200): the legacy fallback

This is the most important peculiarity for interpreting test results. The gateway reads the
per-CRN entitlements from the Runtime API, and the two "no functions" cases are **not equivalent**:

- **Instance has no entitlements configured at all** -> Runtime API responds **HTTP 204**. The
  gateway interprets 204 as "this account/instance has not been migrated to the new system" and
  **falls back to the legacy Django authorization** (`use_legacy_authorization=True`). Under legacy,
  a function can still be visible/usable through Django group membership. This 204 path is the
  expected, correct behavior for not-yet-migrated accounts and must keep working.
- **Instance configured with an explicit empty list** (`functions: []`) -> Runtime API responds
  **HTTP 200** with an empty functions list. The gateway treats this as NTC authorization with zero
  entitlements: a **clean deny**, no legacy fallback.

The practical consequence for the suite: emptying an instance **through the account** (narrow to
empty) lands on the 204 + legacy path, so the function may remain visible. Setting the instance's
own `functions` to `[]` lands on the 200 + clean-deny path. The propagation test relies on this
distinction, and the NONE level is built by PATCHing the instance to `functions: []` (not by
emptying the account).

### Gateway entitlements cache and direct reads

The gateway caches the per-CRN `/functions` result for `RUNTIME_API_CACHE_TTL` seconds
(`function_access_client.py`) under a key derived from `(instance_crn, api_key_hash)`. Because every
level reuses the **same CRN and token**, the cache key is identical across levels, so a stale entry
would make a gateway read return the previous level. The suite therefore assumes the test deployment
runs with the gateway `/functions` cache **disabled** (`RUNTIME_API_CACHE_TTL=0`), so each gateway
read reflects the current instance state.

Given that, an **instance** change is read back **immediately**, with no sleep and no polling:

- `instance.set_entitlements` PATCHes the instance and returns; the permission tests read the gateway
  right after. (The account is widened separately, via `reset_account_with_all_functions`, before the
  PATCH.)
- `assert_runtime_matches` reads the Runtime API once and asserts the entitlements match.

This is sound because the instance PATCH carries an **advancing `timestamp`** (see the Runtime API
ground truth section): it forces the Runtime API to invalidate its per-instance cache and re-sync at
once, so a stored PATCH is reflected by `/functions` immediately.

An **account narrow** is different: it has no such timestamp signal, so its propagation to the Runtime
API is asynchronous. The propagation test therefore **polls** `/functions` after the one account
narrow it performs (step 2), until the narrowed function disappears, instead of reading once.

> Earlier revisions of the suite carried fixed sleeps, broad catalog/Runtime-API polling and a
> function-upload retry-with-abort to absorb propagation lag on **instance** changes. Those were
> compensating for the missing PATCH timestamp: a stored instance PATCH was not reflected by
> `/functions`, so reads had to wait and retry for a re-sync that never reliably came. Once the
> advancing timestamp made the instance re-sync deterministic, that machinery was removed in favor of
> direct reads. The single remaining poll is for the asynchronous account narrow in the propagation
> test.

### Runtime API ground truth (`/functions`)

When the serverless client calls the gateway, the gateway asks the Runtime API which functions the
caller's instance is entitled to (`function_access_client.py`):

```
GET {RUNTIME_API_BASE_URL}/api/v1/functions
Headers:  Service-CRN: <crn>   Authorization: apikey <user_token>
```

with the **same token the user presented to the gateway** (for channel `ibm_quantum_platform` that
is the IBM Cloud API key, i.e. our `GATEWAY_TOKEN`). A `204` means "instance not configured" (legacy
fallback); a `200` returns `{"functions": [{provider, name, permissions[], business_model}], "custom_functions": {"permissions": []}}`.

Note that `custom_functions` may also come back as `null` (not just `{"permissions": []}`): an
instance whose custom grants were cleared is stored with `custom_functions: null` (see the
three-state contract above), and the Runtime API echoes that shape back on the read. Both the
`RuntimeApiClient` here and the gateway's `FunctionAccessClient` must coalesce a `null`
`custom_functions` to an empty permission set rather than dereferencing it.

`runtime_api_client.py` (`RuntimeApiClient`) reproduces this exact call so the tests can read the
ground truth **directly, independent of the gateway**. `test_runtime_api.py` configures the instance
at each level and asserts via `assert_runtime_matches` that the Runtime API exposes **exactly** the
functions, permissions and custom permissions that were written (and that `functions: []` is the
clean `200`-empty deny path, not a `204` fallback). The parsed entitlements are logged on every read
for diagnosis.

`RUNTIME_API_BASE_URL` defaults to `NTC_ADMIN_BASE` (the gateway's own default,
`https://quantum.test.cloud.ibm.com`) and `RUNTIME_API_KEY` defaults to `GATEWAY_TOKEN`; both can be
overridden via environment.

> Operational caution: because the account save narrows every instance synchronously, clearing the
> account while debugging will empty the reconfigurable instance's effective entitlements. Always
> restore the account to its superset (and re-apply the instance level) after any manual experiment.

The resource-controller PATCH must carry an **advancing `timestamp`** (see `ntc_client.py`,
`_next_timestamp`): it is the signal the Runtime API uses to invalidate its per-instance cache and
re-sync. `set_instance_entitlements` reads any timestamp already on the instance and writes one
strictly greater (sent both at the top level and inside `parameters`), so a re-add wins the
account narrow-sync's last-write-wins even if this machine's clock lags the server. Without it a
PATCH that returns `200` and is stored is not reflected by `/functions`.

### Per-level entitlement sets

`conftest.py` defines the entitlements applied at each level. `business_model` must match what the
reused checks expect (`trial` for the user level, `consumption` for the combined/provider levels):

| Level | Instance functions | Custom permissions |
|-------|--------------------|--------------------|
| NONE | `[]` (clean deny via 200) | cleared |
| USER | `instances1-test@trial` with user permissions | `function-custom.{write,run}` |
| PROVIDER | `instances1-test@consumption` with provider permissions | cleared |
| ALL | `instances1-test@consumption` + `instances2-test@consumption`, all permissions | `function-custom.{write,run}` |

The **account superset** grants, by `(provider, name, business_model)` key, a superset of every
level (`instances1-test` at both `trial` and `consumption`, `instances2-test` at `consumption`, plus
the custom permissions), so the broker accepts every instance PATCH and the sync never narrows the
configured level.

### What each test verifies (functional matrix)

Each test class in `test_instance_permissions.py` reconfigures the instance to one level and then
runs the shared assertion battery from `permission_checks.py`. The point is to confirm that the
gateway honors the **exact** set of platform permissions configured on the instance: every endpoint
that the level grants must succeed, and every endpoint it does not grant must be denied with the
expected status (404 for not-visible/not-authorized resources, 403 for provider logs without the
log permission). The function `instances1-test` is the one under test; `instances2-test` exists in
the DB but is only entitled at the ALL level, so it doubles as an isolation check.

| Operation (endpoint) | Required permission | NONE | USER (trial) | PROVIDER | ALL (consumption) |
|----------------------|---------------------|------|--------------|----------|-------------------|
| List in catalog / unfiltered | `function.read` | excluded | listed | excluded | listed |
| Get function by title | `function.read` | 404 | returns it | 404 | returns it |
| Run function | `function.run` | 404 | runs, job `business_model=TRIAL` | 404 | runs, job `business_model=CONSUMPTION` |
| Upload provider function | `function.write` | 404 | 404 | succeeds | succeeds |
| List provider jobs | `function-job.read` | 404 | 404 | succeeds (sees populated job) | succeeds |
| Retrieve a specific job | `function-job.read` | n/a | n/a | succeeds | succeeds |
| Read provider logs | `function-provider-logs.read` | 403 | 403 | succeeds | succeeds |
| List / download provider files | `function-provider-files.read` | 404 | 404 | succeeds | succeeds |
| Upload / delete provider files | `function-provider-files.write` | 404 | 404 | succeeds | succeeds |
| List / download user files | `function-files.read` | 404 | succeeds | 404 | succeeds |
| Upload / delete user files | `function-files.write` | 404 | succeeds | 404 | succeeds |
| Upload custom (serverless) function | `function-custom.write` | 404 | succeeds | 404 | succeeds |
| Run custom (serverless) function | `function-custom.run` | 404 | succeeds | 404 | succeeds |

The matrix is organized by permission level, not one-to-one with the test classes. The two custom
rows under **USER** are not checked by `TestUserInstance` (`UserPermissionChecks` has no custom
tests); they are checked by `TestCustomFunctionInstance` (`CustomFunctionChecks`), which reconfigures
the instance to the **same** USER level (its entitlements include `function-custom.{write,run}`). The
NONE, PROVIDER and ALL custom rows are checked inside their own per-level classes. So every cell is
verified at the stated level, but the USER custom cells live in a dedicated class.

Note on "Retrieve a specific job": the test asserts that `retrieve` succeeds when `function-job.read`
is present, but because every test client shares the same `GATEWAY_TOKEN`, the populated job is authored
by that same user, so the author check alone would already grant access. The test therefore does not
isolate the pure non-author path (`function-job.read` without authorship); that would require a
second user token.

Cross-cutting checks:

- **Provider isolation**: `instances2-test` exists in the DB but is excluded from the
  catalog/unfiltered listings unless it is in the instance entitlements. This is asserted explicitly
  at the USER and PROVIDER levels (where only `instances1-test` is entitled) and the ALL level
  asserts both functions appear. Function-level granularity means access to `instances1-test` never
  implies access to `instances2-test`.
- **Serverless listing ignores platform permissions**: the serverless (own-functions) listing never
  shows a provider function; it only ever returns the caller's own functions. This is asserted at the
  USER, PROVIDER and ALL levels (the `programs/list` author-only path), independently of whether the
  level grants `function.read`.
- **Author always wins** (behaviour, observed indirectly): retrieving your own jobs works through the
  author check, which short-circuits the client lookup. It is exercised via `run` + `get_job_data` at
  the USER and ALL levels rather than by a dedicated no-permission retrieval test.

### Propagation tests (account -> instance)

`test_instance_propagation.py` is black-box and exercises the narrow-only sync semantics directly
through `/functions`, rather than a single level:

| Test | Sequence | What it verifies |
|------|----------|------------------|
| `test_account_narrows_instance_and_does_not_restore` | (1) account superset + instance ALL → (2) narrow the **account** to a sibling function only → (3) re-add the function to the **account** → (4) re-add it to the **instance** | (1) the function is usable; (2) narrowing it out of the account removes it from the instance while the sibling remains, so the function disappears (run → 404) and the sibling stays visible — proving a per-function narrow on the 200 path, not a 204 wipe; (3) re-adding to the account does **not** restore it (sync only narrows); (4) only a direct instance PATCH brings it back. |
| `test_instance_patch_rejected_when_exceeding_account` | account grants only `function.read`; instance PATCH asks for `function.read` + `function.run` | the broker rejects an instance PATCH that exceeds the account grant with a `4xx` validation error. |

> The step-2 narrow deliberately keeps the instance non-empty (the sibling stays). Clearing the
> account entirely would narrow the instance to zero entitlements, which returns 204 and falls back
> to legacy Django authorization, under which the function can remain visible — so an empty-account
> narrow cannot be observed reliably through `/functions`.

### Offline client tests

`test_ntc_client.py` covers `NtcAdminClient` in isolation with `requests_mock` (no network): the two
auth schemes (`apikey` for the account, IAM-exchanged `Bearer` for the instance, with the bearer
cached across calls), the read-modify-write that preserves unrelated fields, the "send only the
target plan" rule, the stripping of server-computed fields, and the three-state `custom_functions`
contract (set / clear-with-null / preserve). These run in CI without staging credentials.

`test_runtime_api_client.py` covers `RuntimeApiClient` the same way: the `Service-CRN` + `apikey`
headers, parsing of the `200` payload (functions, permissions, custom permissions), the `204`
not-configured case, the `200`-with-empty-list case, and a non-200/204 raising `RuntimeApiError`.
