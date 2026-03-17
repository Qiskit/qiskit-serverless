"""Tests program APIs."""

import json
import os
import tempfile

from django.contrib.auth import models
from django.core.files.base import ContentFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from core.model_managers.job_events import JobEventContext, JobEventOrigin, JobEventType
from core.models import Job, JobEvent, Program
from core.services.storage.arguments_storage import ArgumentsStorage
from tests.utils import TestUtils


class TestProgramApi(APITestCase):
    """TestProgramApi."""

    # fixtures = ["tests/fixtures/fixtures.json"]

    def setUp(self):
        # pylint: disable=invalid-name
        """Set up test fixtures and media root path."""
        super().setUp()
        self._temp_directory = tempfile.TemporaryDirectory()
        self.MEDIA_ROOT = self._temp_directory.name
        self.LIMITS_ACTIVE_JOBS_PER_USER = 2

    def tearDown(self):
        self._temp_directory.cleanup()
        super().tearDown()

    def test_programs_non_auth_user(self):
        """Tests program list non-authorized."""
        url = reverse("v1:programs-list")
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_programs_list(self):
        """
            Tests programs list returns only programs user has access to.
            Since user doesn't belong to any group, it will only be self-authored programs.
        """

        user = TestUtils.authorize_client(username="test_user", client=self.client)

        # Create 3 programs for test_user
        TestUtils.create_program(author=user, program_title="ProgramLocked", disabled=True)
        TestUtils.create_program(author=user, program_title="Program")
        TestUtils.create_program(author=user, program_title="ProgramLocked2", disabled=True)
        
        # Create program for another user (not accessible to test_user)
        TestUtils.create_program(author="test_user_2", program_title="OtherUserProgram")

        # no filter applied - all program `test_user` has view permission (owned program in this case) are returned.
        programs_response = self.client.get(reverse("v1:programs-list"), format="json")

        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(programs_response.data), 3)
        self.assertEqual(
            programs_response.data[0].get("title"),
            "ProgramLocked",
        )

    def test_provider_programs_list(self):
        """Tests programs list returns only programs user has access permission for."""

        user = TestUtils.authorize_client(username="test_user_2", client=self.client)

        # Create provider program accessible to test_user_2 as author
        TestUtils.create_program(
            author=user,
            provider_admin="default",
            program_title="Docker-Image-Program",
        )
        
        # Create program by different author (not accessible)
        TestUtils.create_program(
            author="other_user",
            provider_admin="other_provider",
            program_title="Other-Program",
        )

        programs_response = self.client.get(reverse("v1:programs-list"), format="json")

        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(programs_response.data), 1)
        self.assertEqual(
            programs_response.data[0].get("provider"),
            "default",
        )
        self.assertEqual(
            programs_response.data[0].get("title"),
            "Docker-Image-Program",
        )

    def test_provider_programs_catalog_list(self):
        """Tests catalog filter programs list. Catalog filter only returns providers functions that user has access:
            author has permissions for it (by group\instance) and the function has a provider assigned."""

        user = TestUtils.authorize_client(username="test_user_4", client=self.client)
        
        # Add user to runner group for RUN_PROGRAM_PERMISSION
        TestUtils.add_user_to_group(user, "runner")

        # Create 2 provider programs with ibm provider that user has access to
        TestUtils.create_program(
            author="test_user_3",
            provider_admin="ibm",
            program_title="Docker-Image-Program-2",
            instances=["runner"],
        )
        TestUtils.create_program(
            author="test_user_3",
            provider_admin="ibm",
            program_title="Docker-Image-Program-3",
            instances=["runner", "viewer"],
        )

        # Create serverless program (no provider) - should not appear in catalog
        TestUtils.create_program(
            author="test_user_3",
            program_title="Other-Program",
            instances=["runner"],
        )

        programs_response = self.client.get(reverse("v1:programs-list"), {"filter": "catalog"}, format="json")

        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(programs_response.data), 2)
        self.assertEqual(
            programs_response.data[0].get("provider"),
            "ibm",
        )
        self.assertEqual(
            programs_response.data[0].get("title"),
            "Docker-Image-Program-2",
        )
        self.assertEqual(
            programs_response.data[1].get("provider"),
            "ibm",
        )
        self.assertEqual(
            programs_response.data[1].get("title"),
            "Docker-Image-Program-3",
        )

    def test_provider_programs_serverless_list(self):
        """Tests programs list for serverless list. The return criteria is the user is the author of the function and
        there is no provider"""

        user = TestUtils.authorize_client(username="test_user_3", client=self.client)

        # Create serverless program (author=user, no provider) - have permission to run
        TestUtils.create_program(
            author=user,
            program_title="Program",
            entrypoint="program.py",
            artifact="path",
        )
        
        # Create provider program by same user (should not appear in serverless filter)
        TestUtils.create_program(
            author=user,
            provider_admin="default",
            program_title="Provider-Program",
        )

        programs_response = self.client.get(reverse("v1:programs-list"), {"filter": "serverless"}, format="json")

        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(programs_response.data), 1)
        self.assertEqual(
            programs_response.data[0].get("title"),
            "Program",
        )

    def test_run(self):
        """Tests run existing authorized."""

        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            user = TestUtils.authorize_client(username="test_user_3", client=self.client)
            
            # Create program with trial_instances
            TestUtils.create_program(
                author=user,
                program_title="Program",
                entrypoint="program.py",
                artifact="path",
                trial_instances=["runner"],
            )
            
            # Add user to runner group for trial access
            TestUtils.add_user_to_group(user, "runner")
            
            arguments = json.dumps({"MY_ARGUMENT_KEY": "MY_ARGUMENT_VALUE"})
            programs_response = self.client.post(
                "/api/v1/programs/run/",
                data={
                    "title": "Program",
                    "arguments": arguments,
                    "config": {
                        "workers": None,
                        "min_workers": 1,
                        "max_workers": 5,
                        "auto_scaling": True,
                    },
                },
                format="json",
            )
            job_id = programs_response.data.get("id")
            job = Job.objects.get(id=job_id)
            env_vars = json.loads(job.env_vars)

            self.assertEqual(job.status, Job.QUEUED)
            self.assertEqual(job.trial, True)
            self.assertEqual(env_vars["ENV_ACCESS_TRIAL"], "True")
            self.assertEqual(job.config.min_workers, 1)
            self.assertEqual(job.config.max_workers, 5)
            self.assertEqual(job.config.workers, None)
            self.assertEqual(job.config.auto_scaling, True)

            program = Program.objects.get(title="Program", author=user)
            arguments_storage = ArgumentsStorage(user.username, program.title, None)
            stored_arguments = arguments_storage.get(job.id)

            self.assertEqual(stored_arguments, arguments)

            # Verify arguments are stored in the correct folder path
            expected_arguments_path = os.path.join(self.MEDIA_ROOT, user.username, "arguments")
            self.assertEqual(arguments_storage.absolute_path, expected_arguments_path)

            job_events = JobEvent.objects.filter(job=job_id)
            self.assertEqual(len(job_events), 1)
            self.assertEqual(job_events[0].event_type, JobEventType.STATUS_CHANGE)
            self.assertEqual(job_events[0].data["status"], Job.QUEUED)
            self.assertEqual(job_events[0].origin, JobEventOrigin.API)
            self.assertEqual(job_events[0].context, JobEventContext.RUN_PROGRAM)

    def test_provider_run(self):
        """Tests run existing authorized."""

        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            user = TestUtils.authorize_client(username="test_user_2", client=self.client)

            # Create program with provider and env_vars
            program = TestUtils.create_program(
                author=user,
                provider_admin="default",
                program_title="Docker-Image-Program",
                image="icr.io/awesome-namespace/awesome-title",
                env_vars=json.dumps({"PROGRAM_ENV1": "VALUE1", "PROGRAM_ENV2": "VALUE2"}),
            )

            arguments = json.dumps({"MY_ARGUMENT_KEY": "MY_ARGUMENT_VALUE"})
            programs_response = self.client.post(
                "/api/v1/programs/run/",
                data={
                    "title": "Docker-Image-Program",
                    "provider": "default",
                    "arguments": arguments,
                    "config": {
                        "workers": None,
                        "min_workers": 1,
                        "max_workers": 5,
                        "auto_scaling": True,
                    },
                },
                format="json",
            )
            job_id = programs_response.data.get("id")
            job = Job.objects.get(id=job_id)
            env_vars = json.loads(job.env_vars)

            self.assertEqual(job.status, Job.QUEUED)
            self.assertEqual(job.trial, False)
            self.assertEqual(env_vars["PROGRAM_ENV1"], "VALUE1")
            self.assertEqual(env_vars["PROGRAM_ENV2"], "VALUE2")
            self.assertEqual(job.config.min_workers, 1)
            self.assertEqual(job.config.max_workers, 5)
            self.assertEqual(job.config.workers, None)
            self.assertEqual(job.config.auto_scaling, True)

            program = Program.objects.get(title="Docker-Image-Program", author=user)
            provider_name = program.provider.name if program.provider else None
            arguments_storage = ArgumentsStorage(user.username, program.title, provider_name)
            stored_arguments = arguments_storage.get(job.id)

            self.assertEqual(stored_arguments, arguments)

            # Verify arguments are stored in the correct folder path for provider
            expected_arguments_path = os.path.join(
                self.MEDIA_ROOT,
                user.username,
                "default",
                "Docker-Image-Program",
                "arguments",
            )
            self.assertEqual(arguments_storage.absolute_path, expected_arguments_path)

            job_events = JobEvent.objects.filter(job=job_id)
            self.assertEqual(len(job_events), 1)
            self.assertEqual(job_events[0].event_type, JobEventType.STATUS_CHANGE)
            self.assertEqual(job_events[0].data["status"], Job.QUEUED)
            self.assertEqual(job_events[0].origin, JobEventOrigin.API)
            self.assertEqual(job_events[0].context, JobEventContext.RUN_PROGRAM)

    def test_active_jobs_queue_limit(self):
        """Tests queue limit."""

        job_kwargs = {
            "title": "Docker-Image-Program-Test",
            "provider": "default",
            "arguments": json.dumps({"MY_ARGUMENT_KEY": "MY_ARGUMENT_VALUE"}),
            "config": {
                "workers": None,
                "min_workers": 1,
                "max_workers": 5,
                "auto_scaling": True,
            },
        }

        def run_program():
            """Runs program"""
            return self.client.post(
                "/api/v1/programs/run/",
                data=job_kwargs,
                format="json",
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.settings(LIMITS_ACTIVE_JOBS_PER_USER=self.LIMITS_ACTIVE_JOBS_PER_USER, MEDIA_ROOT=temp_dir):
                user = TestUtils.authorize_client(username="test_limit_user", client=self.client)

                # our user will have 2 Jobs, one with `QUEUED` status and other in `SUCCEEDED` status.
                job = TestUtils.create_job(author=user, status=Job.SUCCEEDED, **job_kwargs)
                job = TestUtils.create_job(author=user, status=Job.QUEUED, **job_kwargs)
                num_jobs_in_queue = Job.objects.filter(author=user, status__in=Job.ACTIVE_STATUSES).count()

                # Checking that this test will run according to scripts
                assert self.LIMITS_ACTIVE_JOBS_PER_USER > num_jobs_in_queue

                # filling up the queue to the limit
                for _ in range(num_jobs_in_queue, self.LIMITS_ACTIVE_JOBS_PER_USER):
                    programs_response = run_program()
                    assert programs_response.status_code == 200  # ok

                # the user has a job with status `SUCCEEDED`.
                # Checking it doesn't count it towards the limit
                assert (
                    self.LIMITS_ACTIVE_JOBS_PER_USER
                    == Job.objects.filter(author=user, status__in=Job.ACTIVE_STATUSES).count()
                )
                assert Job.objects.filter(author=user).count() > self.LIMITS_ACTIVE_JOBS_PER_USER

                # Failing to add a job to the queue
                programs_response_fail = run_program()
                assert programs_response_fail.status_code == 429  # limit error
                assert (
                    programs_response_fail.data.get("message") == f"Active job limit reached. The maximum allowed is "
                    f"{self.LIMITS_ACTIVE_JOBS_PER_USER}."
                )

                # Changing a queued job status to Fail and check we can submit another job.
                job = Job.objects.filter(author=user, status__in=Job.ACTIVE_STATUSES).first()
                job.status = Job.FAILED
                job.save()

                assert (
                    self.LIMITS_ACTIVE_JOBS_PER_USER
                    > Job.objects.filter(author=user, status__in=Job.ACTIVE_STATUSES).count()
                )

                # lastly adding job to the queue
                programs_response = run_program()
                assert programs_response.status_code == 200  # ok

    def test_run_locked(self):
        """Tests run disabled program."""

        user = TestUtils.authorize_client(username="test_user", client=self.client)
        
        # Create disabled program with custom message
        TestUtils.create_program(
            author=user,
            program_title="ProgramLocked",
            disabled=True,
            disabled_message="Program is locked",
        )

        arguments = json.dumps({"MY_ARGUMENT_KEY": "MY_ARGUMENT_VALUE"})
        programs_response = self.client.post(
            "/api/v1/programs/run/",
            data={
                "title": "ProgramLocked",
                "arguments": arguments,
                "config": {
                    "workers": None,
                    "min_workers": 1,
                    "max_workers": 5,
                    "auto_scaling": True,
                },
            },
            format="json",
        )

        self.assertEqual(programs_response.status_code, status.HTTP_423_LOCKED)
        self.assertEqual(programs_response.data.get("message"), "Program is locked")

        job_events = JobEvent.objects.filter()
        self.assertEqual(len(job_events), 0)

    def test_run_locked_default_msg(self):
        """Tests run disabled program."""

        user = TestUtils.authorize_client(username="test_user", client=self.client)
        
        # Create disabled program without custom message (uses default)
        TestUtils.create_program(
            author=user,
            program_title="ProgramLocked2",
            disabled=True,
        )

        arguments = json.dumps({"MY_ARGUMENT_KEY": "MY_ARGUMENT_VALUE"})
        programs_response = self.client.post(
            "/api/v1/programs/run/",
            data={
                "title": "ProgramLocked2",
                "arguments": arguments,
                "config": {
                    "workers": None,
                    "min_workers": 1,
                    "max_workers": 5,
                    "auto_scaling": True,
                },
            },
            format="json",
        )

        self.assertEqual(programs_response.status_code, status.HTTP_423_LOCKED)
        self.assertEqual(programs_response.data.get("message"), Program.DEFAULT_DISABLED_MESSAGE)

        job_events = JobEvent.objects.filter()
        self.assertEqual(len(job_events), 0)

    def test_upload_private_function(self):
        """Tests upload end-point authorized."""

        fake_file = ContentFile(b"print('Hello World')")
        fake_file.name = "test_run.tar"

        user = TestUtils.authorize_client(username="test_user_2", client=self.client)

        env_vars = json.dumps({"MY_ENV_VAR_KEY": "MY_ENV_VAR_VALUE"})

        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            programs_response = self.client.post(
                "/api/v1/programs/upload/",
                data={
                    "title": "Private function",
                    "entrypoint": "test_user_2_program.py",
                    "dependencies": "[]",
                    "env_vars": env_vars,
                    "artifact": fake_file,
                },
            )
            self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
            self.assertEqual(programs_response.data.get("provider"), None)

    def test_upload_custom_image_without_provider(self):
        """Tests upload end-point authorized."""

        user = TestUtils.authorize_client(username="test_user_2", client=self.client)

        env_vars = json.dumps({"MY_ENV_VAR_KEY": "MY_ENV_VAR_VALUE"})
        programs_response = self.client.post(
            "/api/v1/programs/upload/",
            data={
                "title": "Private function",
                "dependencies": "[]",
                "env_vars": env_vars,
                "image": "icr.io/awesome-namespace/awesome-title",
            },
        )
        self.assertEqual(programs_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_upload_custom_image_without_access_to_the_provider(self):
        """Tests upload end-point authorized."""

        user = TestUtils.authorize_client(username="test_user", client=self.client)
        
        # Create ibm provider (user doesn't have access)
        TestUtils.get_or_create_provider("ibm")

        env_vars = json.dumps({"MY_ENV_VAR_KEY": "MY_ENV_VAR_VALUE"})
        programs_response = self.client.post(
            "/api/v1/programs/upload/",
            data={
                "title": "Private function",
                "dependencies": "[]",
                "env_vars": env_vars,
                "image": "docker.io/awesome-namespace/awesome-title",
                "provider": "ibm",
            },
        )
        self.assertEqual(programs_response.status_code, status.HTTP_404_NOT_FOUND)

        programs_response = self.client.post(
            "/api/v1/programs/upload/",
            data={
                "title": "ibm/Private function",
                "dependencies": "[]",
                "env_vars": env_vars,
                "image": "docker.io/awesome-namespace/awesome-title",
            },
        )
        self.assertEqual(programs_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_upload_provider_function(self):
        """Tests upload end-point authorized."""

        fake_file = ContentFile(b"print('Hello World')")
        fake_file.name = "test_run.tar"

        user = TestUtils.authorize_client(username="test_user_2", client=self.client)
        
        # Create default provider and add user as admin
        provider = TestUtils.get_or_create_provider("default")
        TestUtils.add_user_to_group(user, "default")

        env_vars = json.dumps({"MY_ENV_VAR_KEY": "MY_ENV_VAR_VALUE"})

        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            programs_response = self.client.post(
                "/api/v1/programs/upload/",
                data={
                    "title": "Provider Function",
                    "entrypoint": "test_user_2_program.py",
                    "dependencies": "[]",
                    "env_vars": env_vars,
                    "artifact": fake_file,
                    "provider": "default",
                },
            )
            self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
            self.assertEqual(programs_response.data.get("provider"), "default")

    def test_upload_provider_function_with_title(self):
        """Tests upload end-point authorized."""

        fake_file = ContentFile(b"print('Hello World')")
        fake_file.name = "test_run.tar"

        user = TestUtils.authorize_client(username="test_user_2", client=self.client)
        
        # Create default provider and add user as admin
        provider = TestUtils.get_or_create_provider("default")
        TestUtils.add_user_to_group(user, "default")

        env_vars = json.dumps({"MY_ENV_VAR_KEY": "MY_ENV_VAR_VALUE"})

        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            programs_response = self.client.post(
                "/api/v1/programs/upload/",
                data={
                    "title": "default/Provider Function",
                    "entrypoint": "test_user_3_program.py",
                    "dependencies": "[]",
                    "env_vars": env_vars,
                    "artifact": fake_file,
                },
            )
            self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
            self.assertEqual(programs_response.data.get("provider"), "default")
            self.assertEqual(programs_response.data.get("entrypoint"), "test_user_3_program.py")
            self.assertEqual(programs_response.data.get("title"), "Provider Function")
            self.assertRaises(
                Program.DoesNotExist,
                Program.objects.get,
                title="default/Provider Function",
            )

    def test_upload_authorization_error(self):
        """Tests upload end-point authorized."""

        fake_file = ContentFile(b"print('Hello World')")
        fake_file.name = "test_run.tar"

        user = TestUtils.authorize_client(username="test_user", client=self.client)
        
        # Create default provider (user doesn't have admin access)
        TestUtils.get_or_create_provider("default")

        env_vars = json.dumps({"MY_ENV_VAR_KEY": "MY_ENV_VAR_VALUE"})
        programs_response = self.client.post(
            "/api/v1/programs/upload/",
            data={
                "title": "Provider Function",
                "entrypoint": "test_user_2_program.py",
                "dependencies": "[]",
                "env_vars": env_vars,
                "artifact": fake_file,
                "provider": "default",
            },
        )
        self.assertEqual(programs_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_upload_provider_function_with_description(self):
        """Tests upload end-point authorized."""

        fake_file = ContentFile(b"print('Hello World')")
        fake_file.name = "test_run.tar"

        user = TestUtils.authorize_client(username="test_user_2", client=self.client)
        
        # Create default provider and add user as admin
        TestUtils.get_or_create_provider("default")
        TestUtils.add_user_to_group(user, "default")
        
        # Create another program to make total count 2
        TestUtils.create_program(
            author=user,
            provider_admin="default",
            program_title="Existing Program",
        )

        env_vars = json.dumps({"MY_ENV_VAR_KEY": "MY_ENV_VAR_VALUE"})
        description = "sample function implemented in a custom image"

        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            programs_response = self.client.post(
                "/api/v1/programs/upload/",
                data={
                    "title": "Provider Function",
                    "entrypoint": "test_user_2_program.py",
                    "dependencies": "[]",
                    "env_vars": env_vars,
                    "artifact": fake_file,
                    "provider": "default",
                    "description": description,
                },
            )
            self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
            self.assertEqual(programs_response.data.get("provider"), "default")

            programs_response = self.client.get(reverse("v1:programs-list"), format="json")

            self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(programs_response.data), 2)
            found = False
            for resp_data in programs_response.data:
                if resp_data.get("title") == "Provider Function":
                    self.assertEqual(
                        resp_data.get("description"),
                        description,
                    )
                    found = True
            self.assertTrue(found)

    def test_get_by_title(self):
        user = TestUtils.authorize_client(username="test_user_2", client=self.client)
        
        # Create provider program
        TestUtils.create_program(
            author=user,
            provider_admin="default",
            program_title="Docker-Image-Program",
        )

        # Trying to get a provider function WITHOUT specifying provider should return 404
        # because get_user_function() correctly filters by provider=None
        programs_response = self.client.get(
            "/api/v1/programs/get_by_title/Docker-Image-Program/",
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_404_NOT_FOUND)

        # Getting a provider function WITH provider query param should work
        programs_response_with_provider = self.client.get(
            "/api/v1/programs/get_by_title/Docker-Image-Program/",
            {"provider": "default"},
            format="json",
        )
        self.assertEqual(programs_response_with_provider.data.get("provider"), "default")
        self.assertIsNotNone(programs_response_with_provider.data.get("title"))

        programs_response_non_existing_provider = self.client.get(
            "/api/v1/programs/get_by_title/Docker-Image-Program/",
            {"provider": "non-existing"},
            format="json",
        )
        self.assertEqual(programs_response_non_existing_provider.status_code, 404)

        programs_response_do_not_have_access = self.client.get(
            "/api/v1/programs/get_by_title/Program/",
            {"provider": "non-existing"},
            format="json",
        )
        self.assertEqual(programs_response_do_not_have_access.status_code, 404)

    def test_get_jobs(self):
        """Tests run existing authorized."""

        user_2 = TestUtils.authorize_client(username="test_user_2", client=self.client)
        user_1 = TestUtils.authorize_client(username="test_user", client=self.client)
        
        # Create program w/o provider with 1 job by test_user_2
        program_no_provider = TestUtils.create_program(
            author=user_1,
            program_title="Program-No-Provider",
        )
        TestUtils.create_job(author=user_2, program=program_no_provider)  # add job with status QUEUE
        
        # Create program w/ provider with 2 jobs (1 by test_user_2, 1 by test_user)
        program_with_provider = TestUtils.create_program(
            author=user_2,
            provider_admin="default",
            program_title="Program-With-Provider",
        )
        TestUtils.add_user_to_group(user_2, "default")
        TestUtils.create_job(author=user_2, program=program_with_provider)
        TestUtils.create_job(author=user_1, program=program_with_provider)

        # program w/o provider
        response = self.client.get(
            f"/api/v1/programs/{program_no_provider.id}/get_jobs/",
            format="json",
        )
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # program w/ provider by not author (sees all jobs as program admin)
        response = self.client.get(
            f"/api/v1/programs/{program_with_provider.id}/get_jobs/",
            format="json",
        )
        self.assertEqual(len(response.data), 2)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # program w/ provider by author (sees only own job)
        self.client.force_authenticate(user=user_1)

        response = self.client.get(
            f"/api/v1/programs/{program_with_provider.id}/get_jobs/",
            format="json",
        )
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_upload_private_function_update_without_description(self):
        """Tests upload end-point authorized."""

        fake_file = ContentFile(b"print('Hello World')")
        fake_file.name = "test_run.tar"

        user = TestUtils.authorize_client(username="test_user", client=self.client)
        
        # Create existing program with description
        TestUtils.create_program(
            author=user,
            program_title="Program",
            description="Program description test",
        )

        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            programs_response = self.client.post(
                "/api/v1/programs/upload/",
                data={
                    "title": "Program",
                    "entrypoint": "test_user_2_program.py",
                    "dependencies": "[]",
                    "artifact": fake_file,
                },
            )

            self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
            self.assertEqual(programs_response.data.get("description"), "Program description test")

    def test_upload_private_function_update_description(self):
        """Tests upload end-point authorized."""

        fake_file = ContentFile(b"print('Hello World')")
        fake_file.name = "test_run.tar"

        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)
        description = "New program description test"

        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            programs_response = self.client.post(
                "/api/v1/programs/upload/",
                data={
                    "title": "Program",
                    "entrypoint": "test_user_2_program.py",
                    "description": description,
                    "dependencies": "[]",
                    "artifact": fake_file,
                },
            )

            self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
            self.assertEqual(programs_response.data.get("description"), description)

    def test_run_user_function_with_same_title_as_provider_function(self):
        """
        Tests that when a user has two functions with the same title
        (one without provider and one with provider), running without
        provider correctly uses the user function (provider=None) and
        stores arguments in the correct path.
        """

        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            user = models.User.objects.get(username="test_user_2")
            self.client.force_authenticate(user=user)

            # Create user function (without provider)
            fake_file_user = ContentFile(b"print('User Function')")
            fake_file_user.name = "user_func.tar"

            upload_response_user = self.client.post(
                "/api/v1/programs/upload/",
                data={
                    "title": "duplicate-title",
                    "entrypoint": "main.py",
                    "dependencies": "[]",
                    "artifact": fake_file_user,
                },
            )
            self.assertEqual(upload_response_user.status_code, status.HTTP_200_OK)
            self.assertIsNone(upload_response_user.data.get("provider"))

            # Create provider function (with provider) - same title, same author
            fake_file_provider = ContentFile(b"print('Provider Function')")
            fake_file_provider.name = "provider_func.tar"

            upload_response_provider = self.client.post(
                "/api/v1/programs/upload/",
                data={
                    "title": "duplicate-title",
                    "entrypoint": "main.py",
                    "dependencies": "[]",
                    "artifact": fake_file_provider,
                    "provider": "default",
                },
            )
            self.assertEqual(upload_response_provider.status_code, status.HTTP_200_OK)
            self.assertEqual(upload_response_provider.data.get("provider"), "default")

            # Verify both functions exist
            user_program = Program.objects.get(title="duplicate-title", author=user, provider=None)
            provider_program = Program.objects.get(title="duplicate-title", author=user, provider__name="default")
            self.assertIsNotNone(user_program)
            self.assertIsNotNone(provider_program)
            self.assertNotEqual(user_program.id, provider_program.id)

            # Run the user function (without provider)
            arguments = json.dumps({"test_key": "test_value"})
            run_response = self.client.post(
                "/api/v1/programs/run/",
                data={
                    "title": "duplicate-title",
                    "arguments": arguments,
                    "config": {
                        "workers": None,
                        "min_workers": 1,
                        "max_workers": 5,
                        "auto_scaling": True,
                    },
                },
                format="json",
            )

            self.assertEqual(run_response.status_code, status.HTTP_200_OK)
            job_id = run_response.data.get("id")
            job = Job.objects.get(id=job_id)

            # Verify the job is associated with the USER function (not provider function)
            self.assertEqual(job.program.id, user_program.id)
            self.assertIsNone(job.program.provider)

            # Verify arguments are stored in the correct path (user storage, not provider)
            arguments_storage = ArgumentsStorage(user.username, user_program.title, None)
            stored_arguments = arguments_storage.get(job.id)
            self.assertEqual(stored_arguments, arguments)

            # Verify the storage path is for user function (no provider in path)
            expected_arguments_path = os.path.join(self.MEDIA_ROOT, user.username, "arguments")
            self.assertEqual(arguments_storage.absolute_path, expected_arguments_path)

    def test_program_version_field_returned(self):
        """Tests that the Program `version` field is returned by the API."""

        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)

        # Update fixture program to have a version string
        program = Program.objects.get(title="Docker-Image-Program", author=user)
        program.version = "1.2.3"
        program.save()

        response = self.client.get(
            "/api/v1/programs/get_by_title/Docker-Image-Program/",
            {"provider": "default"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data.get("version"), "1.2.3")

    def test_upload_invalid_version_returns_error(self):
        """Tests upload returns 400 when version is invalid."""

        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            user = models.User.objects.get(username="test_user_2")
            self.client.force_authenticate(user=user)
            env_vars = json.dumps({"MY_ENV_VAR_KEY": "MY_ENV_VAR_VALUE"})
            version = "not_a_version"

            response = self.client.post(
                "/api/v1/programs/upload/",
                data={
                    "title": "Private function",
                    "entrypoint": "test_user_2_program.py",
                    "dependencies": "[]",
                    "env_vars": env_vars,
                    "version": version,
                },
            )

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            # Error message should mention invalid version
            errors = json.dumps(response.data)
            self.assertIn("Invalid version", errors)
