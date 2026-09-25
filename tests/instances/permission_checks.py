# pylint: disable=import-error, invalid-name, line-too-long, no-member, unused-argument
"""Reusable permission assertion mixins for instance-based /functions tests.

Each class groups the assertions expected for a given set of effective permissions.
The classes are fixture-agnostic: they operate on attributes that a concrete test
class must provide via an autouse binding fixture:

  - self.client                 ServerlessClient authenticated against the instance
  - self.provider_name          provider of the test function
  - self.function_title         title of the test function
  - self.custom_function_title  title of the custom (serverless) function (where used)
  - self.populated_job_id       id of a pre-populated job (where used)
  - self.other_function_title   title of a second function not in the entitlements (where used)
  - self.unowned_function_title title of a provider function the caller does NOT own (where used)

This lets the same battery run at every permission level against the single reconfigurable
instance, which each test class drives to its level before binding self.client.
"""

import requests
import pytest
from qiskit_serverless import QiskitFunction
from qiskit_serverless.exception import QiskitServerlessException

# Expected business_model per CRN (must match the Runtime API configuration).
# These come from core.domain.business_models.BusinessModel constants.
BUSINESS_MODEL_USER = "TRIAL"
BUSINESS_MODEL_ALL = "CONSUMPTION"


# Why the deny checks of the provider operations point at a function title that does not exist
# (self.unowned_function_title) instead of the function the suite uploaded:
#
# Since PR #2397 the author of a provider function is an admin of it, so ProviderAccessPolicy grants
# every provider permission on self.function_title (the suite uploads it, so the caller owns it).
# A deny check therefore needs a function the caller does not own, and with a single token the only
# such function is one that does not exist at all.
#
# That works because in every one of these paths the permission check runs BEFORE the function is
# looked up, so the 404 comes from the denied permission and not from the missing row:
#   - gateway/api/use_cases/programs/upload.py: can_upload_function, then create/update.
#   - gateway/api/use_cases/jobs/provider_list.py: can_list_jobs, then Function.objects.get_function.
#   - gateway/api/use_cases/files/provider_{list,download,upload,delete}.py: can_read_files /
#     can_write_files, then the function lookup.
# Both branches raise a NotFoundError subclass, which api/v1/exception_handler.py maps to 404, so
# the two causes are indistinguishable over HTTP.
#
# This is a fragile coupling and worth knowing about: if any of those use cases is ever reordered to
# look the function up first, these checks would keep passing while asserting nothing about
# permissions at all. If you touch that ordering, revisit these checks.


def _assert_404(exc_info):
    """Assert the exception is an HTTP 404 from the gateway."""
    assert "| Code: 404" in str(exc_info.value)


def _assert_download_404(exc_info):
    """Assert the download was denied with a 404.

    provider_file_download uses raise_for_status() so it raises
    requests.exceptions.HTTPError instead of QiskitServerlessException.
    """
    assert "404" in str(exc_info.value)


def _assert_403(exc_info):
    """Assert the exception is an HTTP 403 from the gateway."""
    assert "| Code: 403" in str(exc_info.value)


def contains_function(functions, provider_name, function_title):
    """Return True if the provider function appears in the list."""
    return any(f.title == function_title and f.provider == provider_name for f in functions)


class FunctionOwnershipChecks:
    """Provider operations granted by AUTHORSHIP alone, with no entitlement whatsoever.

    The author of a provider function is an admin of it: ProviderAccessPolicy._check
    (gateway/api/access_policies/providers.py) grants every provider permission when a function row
    exists for that provider and title with author=user, and it does so on both authorization paths
    (legacy Django groups and runtime instance permissions).

    This suite is the only place that contract can be verified end to end against a real deployment,
    and it is well placed to do it: it uploads self.function_title itself with GATEWAY_TOKEN (see
    _populate_provider_function in conftest.py), so the caller owns that function. These checks are
    mixed into the levels that hold NO provider entitlements (NONE and USER) and expect success
    anyway.

    Expected behaviour, all against the function the caller owns:
      - upload → succeeds (no function.write needed).
      - provider_jobs → succeeds (no function-job.read needed).
      - provider_files list/upload/download/delete → succeed (no function-provider-files.* needed).
      - provider_logs of its job → succeeds (no function-provider-logs.read needed).
      - provider_logs of a job of a function owned by somebody else → 403 (skipped unless
        TEST_FOREIGN_JOB_ID is set).
    """

    def test_upload_owned_function_succeeds_by_ownership(self, tmp_path):
        """upload() succeeds on the caller's own function even without function.write."""
        (tmp_path / "main.py").write_text('print("hello")\n')
        fn = QiskitFunction(
            title=self.function_title,
            provider=self.provider_name,
            entrypoint="main.py",
            working_dir=str(tmp_path),
        )
        result = self.client.upload(fn)
        assert result is not None
        assert result.title == self.function_title

    def test_provider_jobs_owned_function_succeeds_by_ownership(self):
        """provider_jobs() succeeds on the caller's own function even without function-job.read."""
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        jobs = self.client.provider_jobs(fn)
        assert isinstance(jobs, list)
        assert any(
            j.job_id == self.populated_job_id for j in jobs
        ), f"Populated job {self.populated_job_id} not found in provider_jobs. Got: {[j.job_id for j in jobs]}"

    def test_provider_files_list_owned_function_succeeds_by_ownership(self):
        """provider_files() succeeds on the caller's own function without function-provider-files.read."""
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        result = self.client.provider_files(fn)
        assert isinstance(result, list)

    def test_provider_file_upload_owned_function_succeeds_by_ownership(self, tmp_path):
        """provider_file_upload() succeeds on the caller's own function without function-provider-files.write."""
        file = tmp_path / "owner_data.txt"
        file.write_text("owner content")
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        result = self.client.provider_file_upload(str(file), fn)
        assert result is not None

    def test_provider_file_download_owned_function_succeeds_by_ownership(self, tmp_path):
        """provider_file_download() succeeds on the caller's own function without function-provider-files.read."""
        file = tmp_path / "owner_dl_test.txt"
        file.write_text("download content")
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        self.client.provider_file_upload(str(file), fn)
        result = self.client.provider_file_download(
            "owner_dl_test.txt", fn, download_location=str(tmp_path), target_name="owner_dl_result.txt"
        )
        assert result is not None
        assert (tmp_path / "owner_dl_result.txt").exists()

    def test_provider_file_delete_owned_function_succeeds_by_ownership(self, tmp_path):
        """provider_file_delete() succeeds on the caller's own function without function-provider-files.write."""
        file = tmp_path / "owner_del_test.txt"
        file.write_text("delete content")
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        self.client.provider_file_upload(str(file), fn)
        self.client.provider_file_delete("owner_del_test.txt", fn)
        remaining = self.client.provider_files(fn)
        assert "owner_del_test.txt" not in remaining

    def test_provider_logs_owned_function_job_succeeds_by_ownership(self):
        """provider_logs() succeeds for a job of the caller's own function without function-provider-logs.read."""
        logs = self.client.provider_logs(self.populated_job_id)
        assert logs is not None

    def test_provider_logs_foreign_job_raises_403(self, foreign_job_id):
        """provider_logs() is denied (403) for a job whose function the caller does not own.

        Ownership does not leak to other people's functions. This needs a job created by another
        identity, so it is driven by TEST_FOREIGN_JOB_ID and skipped when that is not configured.
        """
        with pytest.raises(QiskitServerlessException) as exc:
            self.client.provider_logs(foreign_job_id)
        _assert_403(exc)


class NonePermissionChecks(FunctionOwnershipChecks):
    """
    Instance with NO permissions (empty functions list).

    The deny checks of the provider operations target unowned_function_title, a function the caller
    does not own: on the caller's own function those same operations are granted by authorship, and
    that is asserted by the inherited FunctionOwnershipChecks.

    Expected behaviour:
      - catalog: provider function excluded (no function.read).
      - unfiltered: provider function excluded (no function.read).
      - get_by_title → 404.
      - run → 404.
      - upload of an unowned function → 404.
      - provider_jobs of an unowned function → 404.
      - files → 404 (no function-files.read).
      - file_upload → 404 (no function-files.write).
      - file_download → 404 (no function-files.read).
      - file_delete → 404 (no function-files.write).
      - provider_files of an unowned function → 404.
      - provider_file_upload of an unowned function → 404.
      - provider_file_download of an unowned function → 404.
      - provider_file_delete of an unowned function → 404.
      - upload custom function → 404 (no function-custom.write).
      - run custom function → 404 (no function-custom.run).
      - every provider operation on the caller's OWN function → succeeds (FunctionOwnershipChecks).
    """

    def test_list_catalog_excludes_function(self):
        """Catalog list excludes the function when no permissions are present."""
        functions = self.client.functions(filter="catalog")
        assert not contains_function(
            functions, self.provider_name, self.function_title
        ), f"Expected {self.provider_name}/{self.function_title} NOT in catalog list (no permissions)"

    def test_list_all_excludes_function(self):
        """Unfiltered list excludes the provider function when no permissions are present."""
        functions = self.client.functions()
        assert not contains_function(
            functions, self.provider_name, self.function_title
        ), f"Expected {self.provider_name}/{self.function_title} NOT in unfiltered list (no permissions)"

    def test_get_by_title_raises_404(self):
        """get_by_title is denied (404) when no permissions are present."""
        with pytest.raises(QiskitServerlessException) as exc:
            self.client.function(self.function_title, provider=self.provider_name)
        _assert_404(exc)

    def test_run_raises_404(self):
        """run() is denied (404) when no permissions are present."""
        with pytest.raises(QiskitServerlessException) as exc:
            self.client.run(self.function_title, provider=self.provider_name)
        _assert_404(exc)

    def test_upload_unowned_function_raises_404(self, tmp_path):
        """upload() of a function the caller does not own is denied (404) with no permissions."""
        (tmp_path / "main.py").write_text('print("hello")\n')
        fn = QiskitFunction(
            title=self.unowned_function_title,
            provider=self.provider_name,
            entrypoint="main.py",
            working_dir=str(tmp_path),
        )
        with pytest.raises(QiskitServerlessException) as exc:
            self.client.upload(fn)
        _assert_404(exc)

    def test_provider_jobs_unowned_function_raises_404(self):
        """provider_jobs() of a function the caller does not own is denied (404) with no permissions."""
        fn = QiskitFunction(title=self.unowned_function_title, provider=self.provider_name)
        with pytest.raises(QiskitServerlessException) as exc:
            self.client.provider_jobs(fn)
        _assert_404(exc)

    def test_provider_files_list_unowned_function_raises_404(self):
        """provider_files() of a function the caller does not own is denied (404) with no permissions."""
        fn = QiskitFunction(title=self.unowned_function_title, provider=self.provider_name)
        with pytest.raises(QiskitServerlessException) as exc:
            self.client.provider_files(fn)
        _assert_404(exc)

    def test_provider_file_upload_unowned_function_raises_404(self, tmp_path):
        """provider_file_upload() of a function the caller does not own is denied (404)."""
        file = tmp_path / "data.txt"
        file.write_text("content")
        fn = QiskitFunction(title=self.unowned_function_title, provider=self.provider_name)
        with pytest.raises(QiskitServerlessException) as exc:
            self.client.provider_file_upload(str(file), fn)
        _assert_404(exc)

    def test_provider_file_download_unowned_function_raises_404(self, tmp_path):
        """provider_file_download() of a function the caller does not own is denied (404)."""
        fn = QiskitFunction(title=self.unowned_function_title, provider=self.provider_name)
        with pytest.raises(requests.exceptions.HTTPError) as exc:
            self.client.provider_file_download("nonexistent.txt", fn, download_location=str(tmp_path))
        _assert_download_404(exc)

    def test_provider_file_delete_unowned_function_raises_404(self):
        """provider_file_delete() of a function the caller does not own is denied (404)."""
        fn = QiskitFunction(title=self.unowned_function_title, provider=self.provider_name)
        with pytest.raises(QiskitServerlessException) as exc:
            self.client.provider_file_delete("nonexistent.txt", fn)
        _assert_404(exc)

    def test_files_list_raises_404(self):
        """files() is denied (404) when function-files.read is absent."""
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        with pytest.raises(QiskitServerlessException) as exc:
            self.client.files(fn)
        _assert_404(exc)

    def test_file_upload_raises_404(self, tmp_path):
        """file_upload() is denied (404) when function-files.write is absent."""
        file = tmp_path / "data.txt"
        file.write_text("content")
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        with pytest.raises(QiskitServerlessException) as exc:
            self.client.file_upload(str(file), fn)
        _assert_404(exc)

    def test_file_download_raises_404(self, tmp_path):
        """file_download() is denied (404) when function-files.read is absent."""
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        with pytest.raises(requests.exceptions.HTTPError) as exc:
            self.client.file_download("nonexistent.txt", fn, download_location=str(tmp_path))
        _assert_download_404(exc)

    def test_file_delete_raises_404(self):
        """file_delete() is denied (404) when function-files.write is absent."""
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        with pytest.raises(QiskitServerlessException) as exc:
            self.client.file_delete("nonexistent.txt", fn)
        _assert_404(exc)

    def test_upload_custom_function_raises_404(self, tmp_path):
        """upload() for a custom function is denied (404) when function-custom.write is absent."""
        (tmp_path / "main.py").write_text('print("hello")\n')
        fn = QiskitFunction(
            title=self.custom_function_title,
            entrypoint="main.py",
            working_dir=str(tmp_path),
        )
        with pytest.raises(QiskitServerlessException) as exc:
            self.client.upload(fn)
        _assert_404(exc)

    def test_run_custom_function_raises_404(self):
        """run() for a custom function is denied (404) when function-custom.run is absent.

        The permission check happens before the function lookup, so the 404 is returned
        even if the function does not yet exist in the DB.
        """
        with pytest.raises(QiskitServerlessException) as exc:
            self.client.run(self.custom_function_title)
        _assert_404(exc)

    def test_serverless_list_includes_custom_function(self, populated_custom_function):
        """Serverless list is author-based; no custom permission is needed to see own functions.

        populated_custom_function was uploaded with the same GATEWAY_TOKEN (same author), so the
        custom function must appear even though this instance has no function-custom.* permissions.
        """
        functions = self.client.functions(filter="serverless")
        titles = [f.title for f in functions]
        assert (
            self.custom_function_title in titles
        ), f"Expected {self.custom_function_title!r} in serverless list (author-owned, no permission check), got: {titles}"


class UserPermissionChecks(FunctionOwnershipChecks):
    """
    Instance with USER permissions only:
      function.read, function.run, function-files.read, function-files.write
      business_model: TRIAL

    Expected behaviour:
      - catalog: provider function appears (function.read).
      - unfiltered: provider function appears (function.read).
      - serverless: provider function never appears (serverless ignores permissions, only own functions).
      - Can run (function.run); job is created with business_model=TRIAL.
      - Cannot upload a function it does not own → 404 (no function.write).
      - Cannot list provider jobs of a function it does not own → 404 (no function-job.read).
      - Can always retrieve own jobs (author check, no permission needed).
      - Can list user files (function-files.read).
      - Can upload user files (function-files.write).
      - Can download user files (function-files.read).
      - Can delete user files (function-files.write).
      - provider_files of an unowned function → 404 (no function-provider-files.read).
      - provider_file_upload of an unowned function → 404 (no function-provider-files.write).
      - provider_file_download of an unowned function → 404 (no function-provider-files.read).
      - provider_file_delete of an unowned function → 404 (no function-provider-files.write).
      - every provider operation on the caller's OWN function → succeeds (FunctionOwnershipChecks).

    The deny checks of the provider operations target unowned_function_title: on the caller's own
    function those operations are granted by authorship, asserted by FunctionOwnershipChecks.
    """

    def test_list_catalog_includes_function(self):
        """Catalog list includes the provider function when function.read is present."""
        functions = self.client.functions(filter="catalog")
        assert contains_function(functions, self.provider_name, self.function_title), (
            f"Expected {self.provider_name}/{self.function_title} in catalog list, got: "
            f"{[(f.provider, f.title) for f in functions]}"
        )

    def test_list_all_includes_function(self):
        """Unfiltered list includes the provider function when function.read is present."""
        functions = self.client.functions()
        assert contains_function(
            functions, self.provider_name, self.function_title
        ), f"Expected {self.provider_name}/{self.function_title} in unfiltered list"

    def test_list_catalog_excludes_other_function(self):
        """Catalog list only shows functions explicitly in the instance entitlements.

        other_function_title exists in the DB but is not in this instance's entitlements,
        so it must not appear.
        """
        functions = self.client.functions(filter="catalog")
        assert not contains_function(
            functions, self.provider_name, self.other_function_title
        ), f"Expected {self.provider_name}/{self.other_function_title} NOT in catalog list (not in CRN entitlements)"

    def test_list_all_excludes_other_function(self):
        """Unfiltered list only shows functions explicitly in the instance entitlements."""
        functions = self.client.functions()
        assert not contains_function(
            functions, self.provider_name, self.other_function_title
        ), f"Expected {self.provider_name}/{self.other_function_title} NOT in unfiltered list (not in CRN entitlements)"

    def test_list_serverless_excludes_provider_function(self):
        """Serverless filter never returns provider functions regardless of permissions.

        filter=serverless returns only Function.objects.user_functions(author), which
        filters provider__isnull=True, so provider functions are always excluded.
        """
        functions = self.client.functions(filter="serverless")
        assert not contains_function(
            functions, self.provider_name, self.function_title
        ), f"Expected {self.provider_name}/{self.function_title} NOT in serverless list (has provider)"

    def test_get_by_title_returns_function(self):
        """get_by_title returns the provider function when function.read is present."""
        fn = self.client.function(self.function_title, provider=self.provider_name)
        assert fn is not None
        assert fn.title == self.function_title
        assert fn.provider == self.provider_name

    def test_run_creates_job_with_business_model(self):
        """run() creates a job with the business_model from the instance plan (TRIAL)."""
        job = self.client.run(self.function_title, provider=self.provider_name)
        assert job is not None
        assert job.job_id is not None

        job_data = self.client.get_job_data(job.job_id)
        assert (
            job_data.get("business_model") == BUSINESS_MODEL_USER
        ), f"Expected business_model={BUSINESS_MODEL_USER}, got {job_data.get('business_model')}"

    def test_upload_unowned_function_raises_404(self, tmp_path):
        """upload() of a function the caller does not own is denied (404) when function.write is absent."""
        (tmp_path / "main.py").write_text('print("hello")\n')
        fn = QiskitFunction(
            title=self.unowned_function_title,
            provider=self.provider_name,
            entrypoint="main.py",
            working_dir=str(tmp_path),
        )
        with pytest.raises(QiskitServerlessException) as exc:
            self.client.upload(fn)
        _assert_404(exc)

    def test_provider_jobs_unowned_function_raises_404(self):
        """provider_jobs() of a function the caller does not own is denied (404) without function-job.read."""
        fn = QiskitFunction(title=self.unowned_function_title, provider=self.provider_name)
        with pytest.raises(QiskitServerlessException) as exc:
            self.client.provider_jobs(fn)
        _assert_404(exc)

    def test_provider_files_list_unowned_function_raises_404(self):
        """provider_files() of a function the caller does not own is denied (404).

        user_instance has function-files.read/write but not function-provider-files.read.
        """
        fn = QiskitFunction(title=self.unowned_function_title, provider=self.provider_name)
        with pytest.raises(QiskitServerlessException) as exc:
            self.client.provider_files(fn)
        _assert_404(exc)

    def test_provider_file_upload_unowned_function_raises_404(self, tmp_path):
        """provider_file_upload() of a function the caller does not own is denied (404)."""
        file = tmp_path / "data.txt"
        file.write_text("content")
        fn = QiskitFunction(title=self.unowned_function_title, provider=self.provider_name)
        with pytest.raises(QiskitServerlessException) as exc:
            self.client.provider_file_upload(str(file), fn)
        _assert_404(exc)

    def test_provider_file_download_unowned_function_raises_404(self, tmp_path):
        """provider_file_download() of a function the caller does not own is denied (404)."""
        fn = QiskitFunction(title=self.unowned_function_title, provider=self.provider_name)
        with pytest.raises(requests.exceptions.HTTPError) as exc:
            self.client.provider_file_download("nonexistent.txt", fn, download_location=str(tmp_path))
        _assert_download_404(exc)

    def test_provider_file_delete_unowned_function_raises_404(self):
        """provider_file_delete() of a function the caller does not own is denied (404)."""
        fn = QiskitFunction(title=self.unowned_function_title, provider=self.provider_name)
        with pytest.raises(QiskitServerlessException) as exc:
            self.client.provider_file_delete("nonexistent.txt", fn)
        _assert_404(exc)

    def test_files_list_returns_list(self):
        """files() succeeds when function-files.read is present."""
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        result = self.client.files(fn)
        assert isinstance(result, list)

    def test_file_upload_succeeds(self, tmp_path):
        """file_upload() succeeds when function-files.write is present."""
        file = tmp_path / "data.txt"
        file.write_text("user content")
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        result = self.client.file_upload(str(file), fn)
        assert result is not None

    def test_file_download_succeeds(self, tmp_path):
        """file_download() succeeds when function-files.read is present."""
        file = tmp_path / "dl_test.txt"
        file.write_text("download content")
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        self.client.file_upload(str(file), fn)
        result = self.client.file_download(
            "dl_test.txt", fn, download_location=str(tmp_path), target_name="dl_result.txt"
        )
        assert result is not None
        assert (tmp_path / "dl_result.txt").exists()

    def test_file_delete_succeeds(self, tmp_path):
        """file_delete() succeeds when function-files.write is present."""
        file = tmp_path / "del_test.txt"
        file.write_text("delete content")
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        self.client.file_upload(str(file), fn)
        self.client.file_delete("del_test.txt", fn)
        remaining = self.client.files(fn)
        assert "del_test.txt" not in remaining


class ProviderPermissionChecks:  # pylint: disable=too-many-public-methods
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
      - Can list provider files (function-provider-files.read).
      - Can upload provider files (function-provider-files.write).
      - Can download provider files (function-provider-files.read).
      - Can delete provider files (function-provider-files.write).
      - files → 404 (no function-files.read).
      - file_upload → 404 (no function-files.write).
      - file_download → 404 (no function-files.read).
      - file_delete → 404 (no function-files.write).
    """

    def test_list_catalog_excludes_function(self):
        """Catalog list excludes the function when function.read is absent."""
        functions = self.client.functions(filter="catalog")
        assert not contains_function(
            functions, self.provider_name, self.function_title
        ), f"Expected {self.provider_name}/{self.function_title} NOT in catalog list (no function.read)"

    def test_list_all_excludes_provider_function(self):
        """Unfiltered list excludes the provider function when function.read is absent.

        Note: the list may still contain the user's own serverless functions; we only
        assert that the specific provider function is not present.
        """
        functions = self.client.functions()
        assert not contains_function(
            functions, self.provider_name, self.function_title
        ), f"Expected {self.provider_name}/{self.function_title} NOT in unfiltered list (no function.read)"

    def test_list_catalog_excludes_other_function(self):
        """Catalog list excludes functions not in the instance entitlements."""
        functions = self.client.functions(filter="catalog")
        assert not contains_function(
            functions, self.provider_name, self.other_function_title
        ), f"Expected {self.provider_name}/{self.other_function_title} NOT in catalog list (not in CRN entitlements)"

    def test_list_all_excludes_other_function(self):
        """Unfiltered list excludes functions not in the instance entitlements."""
        functions = self.client.functions()
        assert not contains_function(
            functions, self.provider_name, self.other_function_title
        ), f"Expected {self.provider_name}/{self.other_function_title} NOT in unfiltered list (not in CRN entitlements)"

    def test_get_by_title_raises_404(self):
        """get_by_title is denied (404) when function.read is absent."""
        with pytest.raises(QiskitServerlessException) as exc:
            self.client.function(self.function_title, provider=self.provider_name)
        _assert_404(exc)

    def test_run_raises_404(self):
        """run() is denied (404) when function.run is absent."""
        with pytest.raises(QiskitServerlessException) as exc:
            self.client.run(self.function_title, provider=self.provider_name)
        _assert_404(exc)

    def test_upload_succeeds(self, tmp_path):
        """upload() succeeds when function.write is present."""
        (tmp_path / "main.py").write_text('print("hello")\n')
        fn = QiskitFunction(
            title=self.function_title,
            provider=self.provider_name,
            entrypoint="main.py",
            working_dir=str(tmp_path),
        )
        result = self.client.upload(fn)
        assert result is not None
        assert result.title == self.function_title

    def test_provider_jobs_contains_populated_job(self):
        """provider_jobs() returns the expected jobs when function-job.read is present.

        Verifies that the populated job appears in the list, confirming the endpoint filters
        correctly by function and that function-job.read grants access.
        """
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        jobs = self.client.provider_jobs(fn)
        assert isinstance(jobs, list)
        assert any(
            j.job_id == self.populated_job_id for j in jobs
        ), f"Populated job {self.populated_job_id} not found in provider_jobs. Got: {[j.job_id for j in jobs]}"

    def test_retrieve_job_succeeds(self):
        """retrieve() succeeds when function-job.read is present.

        Note: since all test clients share the same GATEWAY_TOKEN, the populated job is
        authored by the same user and the author check alone would grant access. The
        non-author code path (function-job.read only) requires a separate user token.
        """
        job_data = self.client.get_job_data(self.populated_job_id)
        assert job_data is not None
        assert "status" in job_data

    def test_list_serverless_excludes_provider_function(self):
        """Serverless filter never returns provider functions regardless of permissions."""
        functions = self.client.functions(filter="serverless")
        assert not contains_function(
            functions, self.provider_name, self.function_title
        ), f"Expected {self.provider_name}/{self.function_title} NOT in serverless list (has provider)"

    def test_provider_files_list_returns_list(self):
        """provider_files() succeeds when function-provider-files.read is present."""
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        result = self.client.provider_files(fn)
        assert isinstance(result, list)

    def test_provider_file_upload_succeeds(self, tmp_path):
        """provider_file_upload() succeeds when function-provider-files.write is present."""
        file = tmp_path / "data.txt"
        file.write_text("provider content")
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        result = self.client.provider_file_upload(str(file), fn)
        assert result is not None

    def test_provider_file_download_succeeds(self, tmp_path):
        """provider_file_download() succeeds when function-provider-files.read is present."""
        file = tmp_path / "dl_test.txt"
        file.write_text("download content")
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        self.client.provider_file_upload(str(file), fn)
        result = self.client.provider_file_download(
            "dl_test.txt", fn, download_location=str(tmp_path), target_name="dl_result.txt"
        )
        assert result is not None
        assert (tmp_path / "dl_result.txt").exists()

    def test_provider_file_delete_succeeds(self, tmp_path):
        """provider_file_delete() succeeds when function-provider-files.write is present."""
        file = tmp_path / "del_test.txt"
        file.write_text("delete content")
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        self.client.provider_file_upload(str(file), fn)
        self.client.provider_file_delete("del_test.txt", fn)
        remaining = self.client.provider_files(fn)
        assert "del_test.txt" not in remaining

    def test_provider_logs_succeeds(self):
        """provider_logs() succeeds when function-provider-logs.read is present."""
        logs = self.client.provider_logs(self.populated_job_id)
        assert logs is not None

    def test_files_list_raises_404(self):
        """files() is denied (404) when function-files.read is absent."""
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        with pytest.raises(QiskitServerlessException) as exc:
            self.client.files(fn)
        _assert_404(exc)

    def test_file_upload_raises_404(self, tmp_path):
        """file_upload() is denied (404) when function-files.write is absent."""
        file = tmp_path / "data.txt"
        file.write_text("content")
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        with pytest.raises(QiskitServerlessException) as exc:
            self.client.file_upload(str(file), fn)
        _assert_404(exc)

    def test_file_download_raises_404(self, tmp_path):
        """file_download() is denied (404) when function-files.read is absent."""
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        with pytest.raises(requests.exceptions.HTTPError) as exc:
            self.client.file_download("nonexistent.txt", fn, download_location=str(tmp_path))
        _assert_download_404(exc)

    def test_file_delete_raises_404(self):
        """file_delete() is denied (404) when function-files.write is absent."""
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        with pytest.raises(QiskitServerlessException) as exc:
            self.client.file_delete("nonexistent.txt", fn)
        _assert_404(exc)

    def test_upload_custom_function_raises_404(self, tmp_path):
        """upload() for a custom function is denied (404) when function-custom.write is absent."""
        (tmp_path / "main.py").write_text('print("hello")\n')
        fn = QiskitFunction(
            title=self.custom_function_title,
            entrypoint="main.py",
            working_dir=str(tmp_path),
        )
        with pytest.raises(QiskitServerlessException) as exc:
            self.client.upload(fn)
        _assert_404(exc)

    def test_run_custom_function_raises_404(self):
        """run() for a custom function is denied (404) when function-custom.run is absent.

        The permission check happens before the function lookup, so the 404 is returned
        even if the function does not yet exist in the DB.
        """
        with pytest.raises(QiskitServerlessException) as exc:
            self.client.run(self.custom_function_title)
        _assert_404(exc)

    def test_serverless_list_includes_custom_function(self, populated_custom_function):
        """Serverless list is author-based; no custom permission is needed to see own functions.

        populated_custom_function was uploaded with the same GATEWAY_TOKEN (same author), so the
        custom function must appear even though this instance has no function-custom.* permissions.
        """
        functions = self.client.functions(filter="serverless")
        titles = [f.title for f in functions]
        assert (
            self.custom_function_title in titles
        ), f"Expected {self.custom_function_title!r} in serverless list (author-owned, no permission check), got: {titles}"


class CombinedPermissionChecks:  # pylint: disable=too-many-public-methods
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
      - Can list provider files (function-provider-files.read).
      - Can upload provider files (function-provider-files.write).
      - Can download provider files (function-provider-files.read).
      - Can delete provider files (function-provider-files.write).
      - Can list user files (function-files.read).
      - Can upload user files (function-files.write).
      - Can download user files (function-files.read).
      - Can delete user files (function-files.write).
    """

    def test_list_catalog_includes_function(self):
        """Catalog list includes the provider function."""
        functions = self.client.functions(filter="catalog")
        assert contains_function(
            functions, self.provider_name, self.function_title
        ), f"Expected {self.provider_name}/{self.function_title} in catalog list"

    def test_list_all_includes_function(self):
        """Unfiltered list includes the provider function."""
        functions = self.client.functions()
        assert contains_function(
            functions, self.provider_name, self.function_title
        ), f"Expected {self.provider_name}/{self.function_title} in unfiltered list"

    def test_list_catalog_includes_both_functions(self):
        """Catalog includes both functions entitled for this CRN.

        combined_instance has function.read for instances1-test and instances2-test.
        Both must appear, confirming that multi-function entitlements work correctly.
        The isolation guarantee (user/provider cannot see instances2-test) is verified
        in TestUserInstance and TestProviderInstance.
        """
        functions = self.client.functions(filter="catalog")
        assert contains_function(
            functions, self.provider_name, self.function_title
        ), f"Expected {self.provider_name}/{self.function_title} in catalog list"
        assert contains_function(
            functions, self.provider_name, self.other_function_title
        ), f"Expected {self.provider_name}/{self.other_function_title} in catalog list (entitled for combined_instance)"

    def test_list_all_includes_both_functions(self):
        """Unfiltered list includes both functions entitled for this CRN."""
        functions = self.client.functions()
        assert contains_function(
            functions, self.provider_name, self.function_title
        ), f"Expected {self.provider_name}/{self.function_title} in unfiltered list"
        assert contains_function(
            functions, self.provider_name, self.other_function_title
        ), f"Expected {self.provider_name}/{self.other_function_title} in unfiltered list (entitled for combined_instance)"

    def test_list_serverless_excludes_provider_function(self):
        """Serverless filter never returns provider functions regardless of permissions."""
        functions = self.client.functions(filter="serverless")
        assert not contains_function(
            functions, self.provider_name, self.function_title
        ), f"Expected {self.provider_name}/{self.function_title} NOT in serverless list (has provider)"

    def test_get_by_title_returns_function(self):
        """get_by_title returns the provider function."""
        fn = self.client.function(self.function_title, provider=self.provider_name)
        assert fn is not None
        assert fn.title == self.function_title
        assert fn.provider == self.provider_name

    def test_run_creates_job_with_business_model(self):
        """run() creates a job with the business_model from the instance plan (CONSUMPTION)."""
        job = self.client.run(self.function_title, provider=self.provider_name)
        assert job is not None
        assert job.job_id is not None

        job_data = self.client.get_job_data(job.job_id)
        assert (
            job_data.get("business_model") == BUSINESS_MODEL_ALL
        ), f"Expected business_model={BUSINESS_MODEL_ALL}, got {job_data.get('business_model')}"

    def test_upload_succeeds(self, tmp_path):
        """upload() succeeds with full permissions."""
        (tmp_path / "main.py").write_text('print("hello")\n')
        fn = QiskitFunction(
            title=self.function_title,
            provider=self.provider_name,
            entrypoint="main.py",
            working_dir=str(tmp_path),
        )
        result = self.client.upload(fn)
        assert result is not None
        assert result.title == self.function_title

    def test_provider_jobs_contains_populated_job(self):
        """provider_jobs() returns the expected jobs with full permissions."""
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        jobs = self.client.provider_jobs(fn)
        assert isinstance(jobs, list)
        assert any(
            j.job_id == self.populated_job_id for j in jobs
        ), f"Populated job {self.populated_job_id} not found in provider_jobs. Got: {[j.job_id for j in jobs]}"

    def test_retrieve_job_succeeds(self):
        """retrieve() succeeds with full permissions."""
        job_data = self.client.get_job_data(self.populated_job_id)
        assert job_data is not None
        assert "status" in job_data

    def test_provider_logs_succeeds(self):
        """provider_logs() succeeds with full permissions."""
        logs = self.client.provider_logs(self.populated_job_id)
        assert logs is not None

    def test_provider_files_list_returns_list(self):
        """provider_files() succeeds with full permissions."""
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        result = self.client.provider_files(fn)
        assert isinstance(result, list)

    def test_provider_file_upload_succeeds(self, tmp_path):
        """provider_file_upload() succeeds with full permissions."""
        file = tmp_path / "data.txt"
        file.write_text("combined content")
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        result = self.client.provider_file_upload(str(file), fn)
        assert result is not None

    def test_provider_file_download_succeeds(self, tmp_path):
        """provider_file_download() succeeds with full permissions."""
        file = tmp_path / "dl_test.txt"
        file.write_text("download content")
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        self.client.provider_file_upload(str(file), fn)
        result = self.client.provider_file_download(
            "dl_test.txt", fn, download_location=str(tmp_path), target_name="dl_result.txt"
        )
        assert result is not None
        assert (tmp_path / "dl_result.txt").exists()

    def test_provider_file_delete_succeeds(self, tmp_path):
        """provider_file_delete() succeeds with full permissions."""
        file = tmp_path / "del_test.txt"
        file.write_text("delete content")
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        self.client.provider_file_upload(str(file), fn)
        self.client.provider_file_delete("del_test.txt", fn)
        remaining = self.client.provider_files(fn)
        assert "del_test.txt" not in remaining

    def test_files_list_returns_list(self):
        """files() succeeds with full permissions."""
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        result = self.client.files(fn)
        assert isinstance(result, list)

    def test_file_upload_succeeds(self, tmp_path):
        """file_upload() succeeds with full permissions."""
        file = tmp_path / "data.txt"
        file.write_text("combined content")
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        result = self.client.file_upload(str(file), fn)
        assert result is not None

    def test_file_download_succeeds(self, tmp_path):
        """file_download() succeeds with full permissions."""
        file = tmp_path / "dl_test.txt"
        file.write_text("download content")
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        self.client.file_upload(str(file), fn)
        result = self.client.file_download(
            "dl_test.txt", fn, download_location=str(tmp_path), target_name="dl_result.txt"
        )
        assert result is not None
        assert (tmp_path / "dl_result.txt").exists()

    def test_file_delete_succeeds(self, tmp_path):
        """file_delete() succeeds with full permissions."""
        file = tmp_path / "del_test.txt"
        file.write_text("delete content")
        fn = QiskitFunction(title=self.function_title, provider=self.provider_name)
        self.client.file_upload(str(file), fn)
        self.client.file_delete("del_test.txt", fn)
        remaining = self.client.files(fn)
        assert "del_test.txt" not in remaining

    def test_upload_custom_function_succeeds(self, tmp_path):
        """upload() for a custom function succeeds when function-custom.write is present."""
        (tmp_path / "main.py").write_text('print("hello")\n')
        fn = QiskitFunction(
            title=self.custom_function_title,
            entrypoint="main.py",
            working_dir=str(tmp_path),
        )
        result = self.client.upload(fn)
        assert result is not None
        assert result.title == self.custom_function_title

    def test_run_custom_function_succeeds(self, populated_custom_function):
        """run() creates a job for the custom function when function-custom.run is present."""
        job = self.client.run(self.custom_function_title)
        assert job is not None
        assert job.job_id is not None

    def test_serverless_list_includes_custom_function(self, populated_custom_function):
        """Serverless filter returns the custom function owned by the authenticated user."""
        functions = self.client.functions(filter="serverless")
        titles = [f.title for f in functions]
        assert (
            self.custom_function_title in titles
        ), f"Expected {self.custom_function_title!r} in serverless list, got: {titles}"


class CustomFunctionChecks:
    """
    Verifies that function-custom.write and function-custom.run work correctly.
    Bound to a client that has both custom permissions alongside its user permissions.

    Expected behaviour:
      - upload() for a custom function succeeds (function-custom.write).
      - run() for a custom function succeeds (function-custom.run).
      - serverless list includes the uploaded custom function.
    """

    def test_upload_custom_function_succeeds(self, tmp_path):
        """upload() succeeds when function-custom.write is present."""
        (tmp_path / "main.py").write_text('print("hello")\n')
        fn = QiskitFunction(
            title=self.custom_function_title,
            entrypoint="main.py",
            working_dir=str(tmp_path),
        )
        result = self.client.upload(fn)
        assert result is not None
        assert result.title == self.custom_function_title

    def test_run_custom_function_succeeds(self, populated_custom_function):
        """run() creates a job for the custom function when function-custom.run is present."""
        job = self.client.run(self.custom_function_title)
        assert job is not None
        assert job.job_id is not None

    def test_serverless_list_includes_custom_function(self, populated_custom_function):
        """Serverless filter returns the custom function owned by the authenticated user."""
        functions = self.client.functions(filter="serverless")
        titles = [f.title for f in functions]
        assert (
            self.custom_function_title in titles
        ), f"Expected {self.custom_function_title!r} in serverless list, got: {titles}"
