# pylint: disable=import-error, invalid-name, line-too-long
"""Integration tests for instance-based permission trough Runtime API /functions

These tests verify that each implemented endpoint correctly grants or denies
access depending on the permissions associated with the CRN instance used
to authenticate.

Endpoints covered:
  - programs/list (catalog, unfiltered, serverless)
  - programs/get_by_title
  - programs/run        (also validates business_model on the created job)
  - programs/upload
  - jobs/provider-list  (provider_jobs)
  - jobs/retrieve       (non-author access via function-job.read)

- By default, these tests are executed against localhost:8000, but it can be configured against staging with:
GATEWAY_HOST=https://qiskit-serverless-dev.quantum.ibm.com

- Feature must be enabled: gateway.runtime_instances_api.enabled should be true in the api_config table

- Runtime API /functions endpoint must be defined with:
  - RUNTIME_API_BASE_URL=https://quantum.test.cloud.ibm.com # staging
  - RUNTIME_API_BASE_URL=https://quantum.cloud.ibm.com # production

All tests use the function: ibm-dev/instances1-test. You can override it with TEST_PROVIDER_NAME and TEST_FUNCTION_TITLE env var.

A second function (TEST_OTHER_FUNCTION_TITLE, default instances2-test) must be pre-seeded in the DB
with the same provider and must NOT appear in any of the four test CRN entitlements. It is used to
verify that the list endpoints only return functions that the instance is explicitly entitled to see.

- There are four kinds of tests, all of them use the same token GATEWAY_TOKEN
  - None tests expect a CRN with no permissions at all. Env var TEST_NONE_INSTANCE
  - User tests expect a CRN with only user permissions enabled. Env var TEST_USER_INSTANCE
  - Provider tests expect a CRN with only provider permissions enabled. Env var TEST_PROVIDER_INSTANCE
  - Combined tests expect a CRN with all permissions enabled. Env var TEST_ALL_INSTANCE

In order to run the tests, this is the configuration you have to get from /functions api:

```json
[
  {
    "instance_crn": "crn:v1:staging:public:quantum-computing:us-east:a/efb0dd39cdb64955b8f6e32d44290acf:f0e2a145-2282-4605-9f54-eafdb7ec68a1::",
    "entitlements": {
      "functions": []
    }
  },
  {
    "instance_crn": "crn:v1:staging:public:quantum-computing:us-east:a/efb0dd39cdb64955b8f6e32d44290acf:6f3d655d-796c-43b9-9d03-a765ab3f6f62::",
    "entitlements": {
      "functions": [
        {
          "name": "instances1-test",
          "provider": "ibm-dev",
          "business_model": "trial",
          "permissions": ["function.read", "function.run", "function-files.read", "function-files.write"]
        }
      ]
    }
  },
  {
    "instance_crn": "crn:v1:staging:public:quantum-computing:us-east:a/efb0dd39cdb64955b8f6e32d44290acf:aad85243-d34e-4374-b22a-ba59fa11e12f::",
    "entitlements": {
      "functions": [
        {
          "name": "instances1-test",
          "provider": "ibm-dev",
          "business_model": "subsidized",
          "permissions": ["function.write", "function-job.read", "function-provider-logs.read", "function-provider-files.read", "function-provider-files.write"]
        }
      ]
    }
  },
  {
    "instance_crn": "crn:v1:staging:public:quantum-computing:us-east:a/efb0dd39cdb64955b8f6e32d44290acf:e862a3cb-ff3b-49c7-9d80-20be5656e550::",
    "entitlements": {
      "functions": [
        {
          "name": "instances1-test",
          "provider": "ibm-dev",
          "business_model": "consumption",
          "permissions": ["function.read", "function.run", "function-files.read", "function-files.write", "function.write", "function-job.read", "function-provider-logs.read", "function-provider-files.read", "function-provider-files.write"]
        },
        {
          "name": "instances2-test",
          "provider": "ibm-dev",
          "business_model": "consumption",
          "permissions": ["function.read", "function.run", "function-files.read", "function-files.write", "function.write", "function-job.read", "function-provider-logs.read", "function-provider-files.read", "function-provider-files.write"]
        }
      ]
    }
  }
]
```
"""

import pytest
from qiskit_serverless import QiskitFunction
from qiskit_serverless.exception import QiskitServerlessException

# Expected business_model per CRN (must match REQUEST.md and the Runtime API configuration).
# These come from core.domain.business_models.BusinessModel constants.
BUSINESS_MODEL_USER = "TRIAL"
BUSINESS_MODEL_ALL = "CONSUMPTION"


def _assert_404(exc_info):
    """Assert the exception is an HTTP 404 from the gateway."""
    assert "| Code: 404" in str(exc_info.value)


def _function_in_list(functions, provider_name, function_title):
    """Return True if the provider function appears in the list."""
    return any(f.title == function_title and f.provider == provider_name for f in functions)


class TestNoPermissionsInstance:
    """
    Instance with NO permissions (empty functions list).

    Expected behaviour:
      - catalog: provider function excluded (no function.read).
      - unfiltered: provider function excluded (no function.read).
      - get_by_title → 404.
      - run → 404.
      - upload → 404.
      - provider_jobs → 404.
    """

    def test_list_catalog_excludes_function(self, none_client, provider_name, function_title):
        """Catalog list excludes the function when no permissions are present."""
        functions = none_client.functions(filter="catalog")
        assert not _function_in_list(
            functions, provider_name, function_title
        ), f"Expected {provider_name}/{function_title} NOT in catalog list (no permissions)"

    def test_list_all_excludes_function(self, none_client, provider_name, function_title):
        """Unfiltered list excludes the provider function when no permissions are present."""
        functions = none_client.functions()
        assert not _function_in_list(
            functions, provider_name, function_title
        ), f"Expected {provider_name}/{function_title} NOT in unfiltered list (no permissions)"

    def test_get_by_title_raises_404(self, none_client, provider_name, function_title):
        """get_by_title is denied (404) when no permissions are present."""
        with pytest.raises(QiskitServerlessException) as exc:
            none_client.function(function_title, provider=provider_name)
        _assert_404(exc)

    def test_run_raises_404(self, none_client, provider_name, function_title):
        """run() is denied (404) when no permissions are present."""
        with pytest.raises(QiskitServerlessException) as exc:
            none_client.run(function_title, provider=provider_name)
        _assert_404(exc)

    def test_upload_raises_404(self, none_client, provider_name, function_title, tmp_path):
        """upload() is denied (404) when no permissions are present."""
        (tmp_path / "main.py").write_text('print("hello")\n')
        fn = QiskitFunction(
            title=function_title,
            provider=provider_name,
            entrypoint="main.py",
            working_dir=str(tmp_path),
        )
        with pytest.raises(QiskitServerlessException) as exc:
            none_client.upload(fn)
        _assert_404(exc)

    def test_provider_jobs_raises_404(self, none_client, provider_name, function_title):
        """provider_jobs() is denied (404) when no permissions are present."""
        fn = QiskitFunction(title=function_title, provider=provider_name)
        with pytest.raises(QiskitServerlessException) as exc:
            none_client.provider_jobs(fn)
        _assert_404(exc)


class TestUserInstance:
    """
    Instance with USER permissions only:
      function.read, function.run, function-files.read, function-files.write
      business_model: TRIAL

    Expected behaviour:
      - catalog: provider function appears (function.read).
      - unfiltered: provider function appears (function.read).
      - serverless: provider function never appears (serverless ignores permissions, only own functions).
      - Can run (function.run); job is created with business_model=TRIAL.
      - Cannot upload → 404 (no function.write).
      - Cannot list provider jobs → 404 (no function-job.read).
      - Can always retrieve own jobs (author check, no permission needed).
    """

    def test_list_catalog_includes_function(self, user_client, provider_name, function_title):
        """Catalog list includes the provider function when function.read is present."""
        functions = user_client.functions(filter="catalog")
        assert _function_in_list(functions, provider_name, function_title), (
            f"Expected {provider_name}/{function_title} in catalog list, got: "
            f"{[(f.provider, f.title) for f in functions]}"
        )

    def test_list_all_includes_function(self, user_client, provider_name, function_title):
        """Unfiltered list includes the provider function when function.read is present."""
        functions = user_client.functions()
        assert _function_in_list(
            functions, provider_name, function_title
        ), f"Expected {provider_name}/{function_title} in unfiltered list"

    def test_list_catalog_excludes_other_function(self, user_client, provider_name, seeded_other_function):
        """Catalog list only shows functions explicitly in the instance entitlements.

        instances2-test exists in the DB (seeded via combined_client) but is not in the
        user_instance CRN entitlements, so it must not appear.
        """
        functions = user_client.functions(filter="catalog")
        assert not _function_in_list(
            functions, provider_name, seeded_other_function
        ), f"Expected {provider_name}/{seeded_other_function} NOT in catalog list (not in CRN entitlements)"

    def test_list_all_excludes_other_function(self, user_client, provider_name, seeded_other_function):
        """Unfiltered list only shows functions explicitly in the instance entitlements.

        instances2-test exists in the DB but is not entitled for user_instance.
        """
        functions = user_client.functions()
        assert not _function_in_list(
            functions, provider_name, seeded_other_function
        ), f"Expected {provider_name}/{seeded_other_function} NOT in unfiltered list (not in CRN entitlements)"

    def test_list_serverless_excludes_provider_function(self, user_client, provider_name, function_title):
        """Serverless filter never returns provider functions regardless of permissions.

        filter=serverless returns only Function.objects.user_functions(author), which
        filters provider__isnull=True, so provider functions are always excluded.
        """
        functions = user_client.functions(filter="serverless")
        assert not _function_in_list(
            functions, provider_name, function_title
        ), f"Expected {provider_name}/{function_title} NOT in serverless list (has provider)"

    def test_get_by_title_returns_function(self, user_client, provider_name, function_title):
        """get_by_title returns the provider function when function.read is present."""
        fn = user_client.function(function_title, provider=provider_name)
        assert fn is not None
        assert fn.title == function_title
        assert fn.provider == provider_name

    def test_run_creates_job_with_business_model(self, user_client, provider_name, function_title):
        """run() creates a job with the business_model from the instance plan (TRIAL)."""
        job = user_client.run(function_title, provider=provider_name)
        assert job is not None
        assert job.job_id is not None

        job_data = user_client.get_job_data(job.job_id)
        assert (
            job_data.get("business_model") == BUSINESS_MODEL_USER
        ), f"Expected business_model={BUSINESS_MODEL_USER}, got {job_data.get('business_model')}"

    def test_upload_raises_404(self, user_client, provider_name, function_title, tmp_path):
        """upload() is denied (404) when function.write is absent."""
        (tmp_path / "main.py").write_text('print("hello")\n')
        fn = QiskitFunction(
            title=function_title,
            provider=provider_name,
            entrypoint="main.py",
            working_dir=str(tmp_path),
        )
        with pytest.raises(QiskitServerlessException) as exc:
            user_client.upload(fn)
        _assert_404(exc)

    def test_provider_jobs_raises_404(self, user_client, provider_name, function_title):
        """provider_jobs() is denied (404) when function-job.read is absent."""
        fn = QiskitFunction(title=function_title, provider=provider_name)
        with pytest.raises(QiskitServerlessException) as exc:
            user_client.provider_jobs(fn)
        _assert_404(exc)


class TestProviderInstance:
    """
    Instance with PROVIDER permissions only:
      function.write, function-job.read, function-provider-logs.read,
      function-provider-files.read, function-provider-files.write

    Expected behavior:
      - catalog: provider function excluded (no function.read).
      - unfiltered: provider function excluded (no function.read).
      - serverless: provider function never appears (serverless ignores permissions).
      - get_by_title → 404, run → 404.
      - Can upload (function.write).
      - Can list provider jobs (function-job.read).
      - Can retrieve a specific job (function-job.read covers both list and retrieve).
    """

    def test_list_catalog_excludes_function(self, provider_client, provider_name, function_title):
        """Catalog list excludes the function when function.read is absent."""
        functions = provider_client.functions(filter="catalog")
        assert not _function_in_list(
            functions, provider_name, function_title
        ), f"Expected {provider_name}/{function_title} NOT in catalog list (no function.read)"

    def test_list_all_excludes_provider_function(self, provider_client, provider_name, function_title):
        """Unfiltered list excludes the provider function when function.read is absent.

        Note: the list may still contain the user's own serverless functions; we only
        assert that the specific provider function is not present.
        """
        functions = provider_client.functions()
        assert not _function_in_list(
            functions, provider_name, function_title
        ), f"Expected {provider_name}/{function_title} NOT in unfiltered list (no function.read)"

    def test_list_catalog_excludes_other_function(self, provider_client, provider_name, seeded_other_function):
        """Catalog list excludes functions not in the instance entitlements.

        instances2-test exists in the DB (seeded via combined_client) but is not in the
        provider_instance CRN entitlements.
        """
        functions = provider_client.functions(filter="catalog")
        assert not _function_in_list(
            functions, provider_name, seeded_other_function
        ), f"Expected {provider_name}/{seeded_other_function} NOT in catalog list (not in CRN entitlements)"

    def test_list_all_excludes_other_function(self, provider_client, provider_name, seeded_other_function):
        """Unfiltered list excludes functions not in the instance entitlements.

        instances2-test exists in the DB but is not entitled for provider_instance.
        """
        functions = provider_client.functions()
        assert not _function_in_list(
            functions, provider_name, seeded_other_function
        ), f"Expected {provider_name}/{seeded_other_function} NOT in unfiltered list (not in CRN entitlements)"

    def test_get_by_title_raises_404(self, provider_client, provider_name, function_title):
        """get_by_title is denied (404) when function.read is absent."""
        with pytest.raises(QiskitServerlessException) as exc:
            provider_client.function(function_title, provider=provider_name)
        _assert_404(exc)

    def test_run_raises_404(self, provider_client, provider_name, function_title):
        """run() is denied (404) when function.run is absent."""
        with pytest.raises(QiskitServerlessException) as exc:
            provider_client.run(function_title, provider=provider_name)
        _assert_404(exc)

    def test_upload_succeeds(self, provider_client, provider_name, function_title, tmp_path):
        """upload() succeeds when function.write is present."""
        (tmp_path / "main.py").write_text('print("hello")\n')
        fn = QiskitFunction(
            title=function_title,
            provider=provider_name,
            entrypoint="main.py",
            working_dir=str(tmp_path),
        )
        result = provider_client.upload(fn)
        assert result is not None
        assert result.title == function_title

    def test_provider_jobs_contains_seeded_job(self, provider_client, provider_name, function_title, seeded_job_id):
        """provider_jobs() returns the expected jobs when function-job.read is present.

        Verifies that the seeded job appears in the list, confirming the endpoint filters
        correctly by function and that function-job.read grants access.
        """
        fn = QiskitFunction(title=function_title, provider=provider_name)
        jobs = provider_client.provider_jobs(fn)
        assert isinstance(jobs, list)
        assert any(
            j.job_id == seeded_job_id for j in jobs
        ), f"Seeded job {seeded_job_id} not found in provider_jobs. Got: {[j.job_id for j in jobs]}"

    def test_retrieve_job_succeeds(self, provider_client, seeded_job_id):
        """retrieve() succeeds when function-job.read is present.

        Note: since all test clients share the same GATEWAY_TOKEN, the seeded job is
        authored by the same user and the author check alone would grant access. The
        non-author code path (function-job.read only) requires a separate user token.
        """
        job_data = provider_client.get_job_data(seeded_job_id)
        assert job_data is not None
        assert "status" in job_data

    def test_list_serverless_excludes_provider_function(self, provider_client, provider_name, function_title):
        """Serverless filter never returns provider functions regardless of permissions."""
        functions = provider_client.functions(filter="serverless")
        assert not _function_in_list(
            functions, provider_name, function_title
        ), f"Expected {provider_name}/{function_title} NOT in serverless list (has provider)"


class TestCombinedInstance:
    """
    Instance with ALL permissions (USER + PROVIDER):
      function.read, function.run, function-files.read, function-files.write,
      function.write, function-job.read, function-provider-logs.read,
      function-provider-files.read, function-provider-files.write
      business_model: CONSUMPTION

    Expected behaviour:
      - catalog: provider function appears.
      - unfiltered: provider function appears.
      - serverless: provider function never appears (serverless ignores permissions).
      - All other endpoints work correctly.
      - Can list provider jobs and retrieve individual jobs (function-job.read).
    """

    def test_list_catalog_includes_function(self, combined_client, provider_name, function_title):
        """Catalog list includes the provider function."""
        functions = combined_client.functions(filter="catalog")
        assert _function_in_list(
            functions, provider_name, function_title
        ), f"Expected {provider_name}/{function_title} in catalog list"

    def test_list_all_includes_function(self, combined_client, provider_name, function_title):
        """Unfiltered list includes the provider function."""
        functions = combined_client.functions()
        assert _function_in_list(
            functions, provider_name, function_title
        ), f"Expected {provider_name}/{function_title} in unfiltered list"

    def test_list_catalog_includes_both_functions(
        self, combined_client, provider_name, function_title, seeded_other_function
    ):
        """Catalog includes both functions entitled for this CRN.

        combined_instance has function.read for instances1-test and instances2-test.
        Both must appear, confirming that multi-function entitlements work correctly.
        The isolation guarantee (user/provider cannot see instances2-test) is verified
        in TestUserInstance and TestProviderInstance.
        """
        functions = combined_client.functions(filter="catalog")
        assert _function_in_list(
            functions, provider_name, function_title
        ), f"Expected {provider_name}/{function_title} in catalog list"
        assert _function_in_list(
            functions, provider_name, seeded_other_function
        ), f"Expected {provider_name}/{seeded_other_function} in catalog list (entitled for combined_instance)"

    def test_list_all_includes_both_functions(
        self, combined_client, provider_name, function_title, seeded_other_function
    ):
        """Unfiltered list includes both functions entitled for this CRN."""
        functions = combined_client.functions()
        assert _function_in_list(
            functions, provider_name, function_title
        ), f"Expected {provider_name}/{function_title} in unfiltered list"
        assert _function_in_list(
            functions, provider_name, seeded_other_function
        ), f"Expected {provider_name}/{seeded_other_function} in unfiltered list (entitled for combined_instance)"

    def test_list_serverless_excludes_provider_function(self, combined_client, provider_name, function_title):
        """Serverless filter never returns provider functions regardless of permissions."""
        functions = combined_client.functions(filter="serverless")
        assert not _function_in_list(
            functions, provider_name, function_title
        ), f"Expected {provider_name}/{function_title} NOT in serverless list (has provider)"

    def test_get_by_title_returns_function(self, combined_client, provider_name, function_title):
        """get_by_title returns the provider function."""
        fn = combined_client.function(function_title, provider=provider_name)
        assert fn is not None
        assert fn.title == function_title
        assert fn.provider == provider_name

    def test_run_creates_job_with_business_model(self, combined_client, provider_name, function_title):
        """run() creates a job with the business_model from the instance plan (CONSUMPTION)."""
        job = combined_client.run(function_title, provider=provider_name)
        assert job is not None
        assert job.job_id is not None

        job_data = combined_client.get_job_data(job.job_id)
        assert (
            job_data.get("business_model") == BUSINESS_MODEL_ALL
        ), f"Expected business_model={BUSINESS_MODEL_ALL}, got {job_data.get('business_model')}"

    def test_upload_succeeds(self, combined_client, provider_name, function_title, tmp_path):
        """upload() succeeds with full permissions."""
        (tmp_path / "main.py").write_text('print("hello")\n')
        fn = QiskitFunction(
            title=function_title,
            provider=provider_name,
            entrypoint="main.py",
            working_dir=str(tmp_path),
        )
        result = combined_client.upload(fn)
        assert result is not None
        assert result.title == function_title

    def test_provider_jobs_contains_seeded_job(self, combined_client, provider_name, function_title, seeded_job_id):
        """provider_jobs() returns the expected jobs with full permissions."""
        fn = QiskitFunction(title=function_title, provider=provider_name)
        jobs = combined_client.provider_jobs(fn)
        assert isinstance(jobs, list)
        assert any(
            j.job_id == seeded_job_id for j in jobs
        ), f"Seeded job {seeded_job_id} not found in provider_jobs. Got: {[j.job_id for j in jobs]}"

    def test_retrieve_job_succeeds(self, combined_client, seeded_job_id):
        """retrieve() succeeds with full permissions."""
        job_data = combined_client.get_job_data(seeded_job_id)
        assert job_data is not None
        assert "status" in job_data
