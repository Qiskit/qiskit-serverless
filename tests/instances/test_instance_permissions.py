# pylint: disable=import-error, invalid-name
"""
Integration tests for instance-based permission enforcement.

These tests verify that each implemented endpoint correctly grants or denies
access depending on the permissions associated with the CRN instance used
to authenticate.

Endpoints covered:
  - programs/list (catalog, unfiltered, serverless)
  - programs/get_by_title
  - programs/run        (also validates business_model on the created job)
  - programs/upload
  - jobs/provider-list  (provider_jobs)

Run all:
    tox -e instances

Run a specific class:
    pytest -v instances/test_instance_permissions.py::TestUserInstance

Run a specific test:
    pytest -v instances/test_instance_permissions.py::TestCombinedInstance::test_run_creates_job

Run by keyword:
    pytest -v -k "test_run" instances/
"""

import pytest
from qiskit_serverless import QiskitFunction
from qiskit_serverless.exception import QiskitServerlessException

# Expected business_model per CRN (must match REQUEST.md and the Runtime API configuration).
# These come from core.domain.business_models.BusinessModel constants.
BUSINESS_MODEL_USER = "TRIAL"
BUSINESS_MODEL_COMBINED = "CONSUMPTION"


def _assert_404(exc_info):
    """Assert the exception is an HTTP 404 from the gateway."""
    assert "| Code: 404" in str(exc_info.value)


def _function_in_list(functions, provider_name, function_title):
    """Return True if the provider function appears in the list."""
    return any(f.title == function_title and f.provider == provider_name for f in functions)


class TestUserInstance:
    """
    Instance with USER permissions only:
      function.read, function.run, function.job.read, function.files
      business_model: TRIAL

    Expected behaviour:
      - catalog: provider function appears (function.read).
      - unfiltered: provider function appears (function.read).
      - serverless: provider function never appears (serverless ignores permissions, only own functions).
      - Can run (function.run); job is created with business_model=TRIAL.
      - Cannot upload → 404.
      - Cannot list provider jobs → 404.
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
        """upload() is denied (404) when function.provider.upload is absent."""
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
        """provider_jobs() is denied (404) when function.provider.jobs is absent."""
        fn = QiskitFunction(title=function_title, provider=provider_name)
        with pytest.raises(QiskitServerlessException) as exc:
            user_client.provider_jobs(fn)
        _assert_404(exc)


class TestProviderInstance:
    """
    Instance with PROVIDER permissions only:
      function.provider.upload, function.provider.jobs,
      function.provider.logs, function.provider.files

    Expected behavior:
      - Cannot list the provider function in catalog → excluded from list.
      - Cannot list the provider function unfiltered → excluded from list.
      - Cannot retrieve the provider function by title → 404.
      - Cannot run the provider function → 404.
      - Can upload a provider function (function.provider.upload).
      - Can list provider jobs (function.provider.jobs).
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
        """upload() succeeds when function.provider.upload is present."""
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

    def test_provider_jobs_returns_list(self, provider_client, provider_name, function_title):
        """provider_jobs() succeeds when function.provider.jobs is present."""
        fn = QiskitFunction(title=function_title, provider=provider_name)
        jobs = provider_client.provider_jobs(fn)
        assert isinstance(jobs, list)


class TestCombinedInstance:
    """
    Instance with ALL 8 permissions (USER + PROVIDER).
      business_model: CONSUMPTION

    Expected behaviour: every endpoint works correctly.
    """

    def test_list_catalog_includes_function(self, combined_client, provider_name, function_title):
        """Catalog list includes the provider function."""
        functions = combined_client.functions(filter="catalog")
        assert _function_in_list(
            functions, provider_name, function_title
        ), f"Expected {provider_name}/{function_title} in catalog list"

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
            job_data.get("business_model") == BUSINESS_MODEL_COMBINED
        ), f"Expected business_model={BUSINESS_MODEL_COMBINED}, got {job_data.get('business_model')}"

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

    def test_provider_jobs_returns_list(self, combined_client, provider_name, function_title):
        """provider_jobs() returns a list with full permissions."""
        fn = QiskitFunction(title=function_title, provider=provider_name)
        jobs = combined_client.provider_jobs(fn)
        assert isinstance(jobs, list)
