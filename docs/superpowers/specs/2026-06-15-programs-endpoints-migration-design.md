# Programs Endpoints Migration Design

**Date:** 2026-06-15
**Branch:** program-refactor

## Context

The `programs` resource currently lives in a DRF ViewSet (`api/views/programs.py` base + `api/v1/views/programs.py` subclass). The rest of the v1 API has been migrated to standalone function-based endpoints using `@endpoint`, `@api_view`, `@permission_classes`, and `@endpoint_handle_exceptions`, with business logic extracted into use cases that raise domain exceptions. This spec covers migrating the programs endpoints to that same pattern, split into two PRs.

## Scope

### In scope
- `GET /api/v1/programs/` - list functions
- `GET /api/v1/programs/get_by_title/<title>/` - get function by title
- `POST /api/v1/programs/upload/` - upload a function
- `POST /api/v1/programs/run/` - run a function

### Out of scope
- `GET /api/v1/programs/<pk>/get_jobs/` - deprecated endpoint, disappears with the ViewSet in PR 2

---

## PR 1: Read endpoints with use cases

### New files

```
api/use_cases/programs/__init__.py
api/use_cases/programs/list.py          # ListFunctionsUseCase
api/use_cases/programs/get_by_title.py  # GetFunctionByTitleUseCase

api/v1/views/programs/__init__.py
api/v1/views/programs/list.py           # list_programs view
api/v1/views/programs/get_by_title.py   # get_by_title view

tests/api/use_cases/programs/__init__.py
tests/api/use_cases/programs/test_list.py
tests/api/use_cases/programs/test_get_by_title.py
```

### Modified files

- `api/views/programs.py` - remove `list` and `get_by_title` methods
- `api/v1/views/programs.py` - remove `list` and `get_by_title` overrides

The ViewSet remains alive with only `upload`, `run`, and `get_jobs`.

### Use case: ListFunctionsUseCase

```python
def execute(self, user, accessible_functions, type_filter: str | None) -> list[Function]
```

Applies the three filter branches from the current ViewSet verbatim:
- `type_filter == "serverless"`: `Function.objects.user_functions(user)`
- `type_filter == "catalog"`: `Function.objects.provider_functions().with_permission(...)`
- `None`: `Function.objects.with_permission(...)`

No error cases. Returns an empty list if nothing matches.

### Use case: GetFunctionByTitleUseCase

```python
def execute(self, user, accessible_functions, title: str, provider: str | None) -> Function
```

Raises `FunctionNotFoundException` if the function does not exist or the user does not have access. Both cases map to 404 - this is intentional to avoid leaking information about function existence.

Receives `title` and `provider` already separated. The use case does not parse `"provider/title"` strings.

### View: list_programs

`@endpoint("programs", name="programs-list")` / `GET`

Reads `filter` from `request.query_params` directly. No InputSerializer (a single string param needs no validation structure). Serializes output with the existing `v1_serializers.ProgramSerializer`.

### View: get_by_title

`@endpoint("programs/get_by_title/<str:title>", name="programs-get-by-title")` / `GET`

Contains a module-level helper `_parse_title_and_provider` that handles the `"provider/title"` splitting convention. This is input normalization, not business logic, so it stays in the view layer:

```python
def _parse_title_and_provider(title: str, provider: str | None) -> tuple[str, str | None]:
    if provider:
        return sanitize_name(title), sanitize_name(provider)
    parts = title.split("/")
    if len(parts) == 1:
        return sanitize_name(title), None
    return sanitize_name(parts[1]), sanitize_name(parts[0])
```

### Unit tests

Follow the pattern of `tests/api/use_cases/jobs/test_retrieve.py`: pure unit tests, no HTTP client, fixtures create DB objects directly.

**test_list.py:**
- User sees their own functions (filter=serverless)
- User sees provider functions with permission (filter=catalog)
- User sees combined list (no filter)
- Returns empty list if no functions exist

**test_get_by_title.py:**
- Finds user's own function
- Finds provider function with access
- Raises `FunctionNotFoundException` if function does not exist
- Raises `FunctionNotFoundException` if user has no access (same error, not 403)

The `_parse_title_and_provider` helper lives in the view module and is covered by the existing integration tests in `tests/api/test_v1_program.py`, which test the full HTTP path including the `"provider/title"` convention. Those tests are not modified - the URLs do not change so they pass without modification.

---

## PR 2: Write endpoints + ViewSet deletion

### New files

```
api/v1/views/programs/upload.py   # upload view
api/v1/views/programs/run.py      # run view
```

### Deleted files

- `api/views/programs.py`
- `api/v1/views/programs.py`

### Modified files

- `api/v1/urls.py` - remove `router.register(r"programs", ...)` and related imports

### What changes in upload and run

Structural changes only, no business logic changes:
- `self.get_serializer_X(...)` replaced with `v1_serializers.X(...)` directly
- `@endpoint`, `@api_view(["POST"])`, `@permission_classes([permissions.IsAuthenticated])`, `@endpoint_handle_exceptions` added
- `@_trace` decorator removed (it relies on ViewSet `self` context and does not apply to standalone functions)

No new use cases. All validation, permission checks, and error handling stay exactly as they are in the current ViewSet methods.

---

## URL continuity

All URL paths remain identical. The DRF Router and the `RouteRegistry` both produce the same paths, so external clients and existing tests are unaffected.

| Endpoint | URL | Name |
|----------|-----|------|
| list | `programs/` | `programs-list` |
| get_by_title | `programs/get_by_title/<title>/` | `programs-get-by-title` |
| upload | `programs/upload/` | `programs-upload` |
| run | `programs/run/` | `programs-run` |

---

## Error handling

Both use cases raise domain exceptions that `endpoint_handle_exceptions` already handles:
- `FunctionNotFoundException` (subclass of `NotFoundError`) -> 404
- `InvalidAccessException` -> 403 (not used in this migration, but available for future use cases)

The `upload` and `run` views keep their current manual `Response({"message": ...}, status=...)` pattern unchanged.
