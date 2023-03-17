"""Views."""

import json
import os.path
import shutil
import tarfile
import uuid

import requests
from allauth.socialaccount.providers.keycloak.views import KeycloakOAuth2Adapter
from dj_rest_auth.registration.views import SocialLoginView
from django.conf import settings
from django.contrib.auth.models import User  # pylint: disable=imported-auth-user
from ray.dashboard.modules.job.common import JobStatus
from ray.dashboard.modules.job.sdk import JobSubmissionClient
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Program, Job, ComputeResource
from .permissions import IsOwner
from .serializers import ProgramSerializer, JobSerializer


# pylint: disable=too-many-ancestors
class ProgramViewSet(viewsets.ModelViewSet):
    """ProgramViewSet."""

    queryset = Program.objects.all()
    serializer_class = ProgramSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Program.objects.all().filter(author=self.request.user)

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    @action(methods=["POST"], detail=False)
    def run_program(self, request):
        """Runs provided program on compute resources."""

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            # create program
            program = Program(**serializer.data)

            existing_programs = Program.objects.filter(
                author=request.user, title__exact=program.title
            )
            if existing_programs.count() > 0:
                # take existing one
                program = existing_programs.first()
            program.artifact = request.FILES.get("artifact")
            program.author = request.user
            program.save()

            # get available compute resources
            resources = ComputeResource.objects.filter(users__in=[request.user])
            if resources.count() == 0:
                return Response(
                    {"error": "user do not have any resources in account"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            compute_resource = resources.first()

            # start job
            ray_client = JobSubmissionClient(compute_resource.host)
            # unpack data
            with tarfile.open(program.artifact.path) as file:
                extract_folder = os.path.join(
                    settings.MEDIA_ROOT, "tmp", str(uuid.uuid4())
                )
                file.extractall(extract_folder)
            ray_job_id = ray_client.submit_job(
                entrypoint=f"python {program.entrypoint}",
                runtime_env={"working_dir": extract_folder},
            )
            # remote temp data
            if os.path.exists(extract_folder):
                shutil.rmtree(extract_folder)

            job = Job(
                program=program,
                author=request.user,
                ray_job_id=ray_job_id,
                compute_resource=compute_resource,
            )
            job.save()
            return Response(JobSerializer(job).data)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class JobViewSet(viewsets.ModelViewSet):
    """JobViewSet."""

    queryset = Job.objects.all()
    serializer_class = JobSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_queryset(self):
        return Job.objects.all().filter(author=self.request.user)

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    def retrieve(self, request, pk=None):  # pylint: disable=arguments-differ
        queryset = Job.objects.all()
        job: Job = get_object_or_404(queryset, pk=pk)
        serializer = JobSerializer(job)
        if job.compute_resource:
            ray_client = JobSubmissionClient(job.compute_resource.host)
            ray_job_status = ray_client.get_job_status(job.ray_job_id)
            job.status = ray_job_status_to_model_job_status(ray_job_status)
            job.save()
        return Response(serializer.data)

    @action(methods=["POST"], detail=True, permission_classes=[permissions.AllowAny])
    def result(self, request, pk=None):  # pylint: disable=invalid-name,unused-argument
        """Save result of a job."""
        job = self.get_object()
        job.result = json.dumps(request.data.get("result"))
        # job.status = Job.SUCCEEDED
        job.save()
        return Response(JobSerializer(job).data)


def ray_job_status_to_model_job_status(ray_job_status):
    """Maps ray job status to model job status."""

    mapping = {
        JobStatus.PENDING: Job.PENDING,
        JobStatus.RUNNING: Job.RUNNING,
        JobStatus.STOPPED: Job.STOPPED,
        JobStatus.SUCCEEDED: Job.SUCCEEDED,
        JobStatus.FAILED: Job.FAILED,
    }
    return mapping.get(ray_job_status, Job.FAILED)


class KeycloakLogin(SocialLoginView):
    """KeycloakLogin."""

    adapter_class = KeycloakOAuth2Adapter


class KeycloakUsersView(APIView):
    """KeycloakUsersView."""

    queryset = User.objects.all()
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        """Get application token.

        Request: /POST
        Body: {"username": ..., "password": ...}
        """
        keycloak_payload = {
            "grant_type": "password",
            "client_id": settings.SETTINGS_KEYCLOAK_CLIENT_NAME,
            "client_secret": settings.SETTINGS_KEYCLOAK_CLIENT_SECRET,
        }
        keycloak_provider = settings.SOCIALACCOUNT_PROVIDERS.get("keycloak")
        if keycloak_provider is None:
            return Response(
                {
                    "message": "Oops. Provider was not configured correctly on a server side."
                },
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )

        keycloak_url = (
            f"{keycloak_provider.get('KEYCLOAK_URL')}/realms/"
            f"{keycloak_provider.get('KEYCLOAK_REALM')}/"
            f"protocol/openid-connect/token/"
        )
        payload = {**keycloak_payload, **request.data}
        keycloak_response = requests.post(
            keycloak_url,
            data=payload,
            timeout=settings.SETTINGS_KEYCLOAK_REQUESTS_TIMEOUT,
        )
        if not keycloak_response.ok:
            return Response(
                {"message": keycloak_response.text}, status=status.HTTP_400_BAD_REQUEST
            )

        access_token = json.loads(keycloak_response.text).get("access_token")
        if settings.SITE_HOST is None:
            return Response(
                {
                    "message": "Oops. Application was not configured correctly on a server side."
                },
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )

        rest_auth_url = f"{settings.SITE_HOST}/dj-rest-auth/keycloak/"
        rest_auth_response = requests.post(
            rest_auth_url,
            json={"access_token": access_token},
            timeout=settings.SETTINGS_KEYCLOAK_REQUESTS_TIMEOUT,
        )

        if not rest_auth_response.ok:
            return Response(
                {"message": rest_auth_response.text}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(json.loads(rest_auth_response.text))
