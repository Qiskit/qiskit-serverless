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
