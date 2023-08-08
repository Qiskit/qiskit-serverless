"""
Django Rest framework views for api application:
    - Program ViewSet
    - Job ViewSet
    - KeycloakUsers ApiView

Version views inherit from the different views.
"""

import json
import logging

import requests
from allauth.socialaccount.providers.keycloak.views import KeycloakOAuth2Adapter
from dj_rest_auth.registration.views import SocialLoginView
from django.conf import settings
from django.contrib.auth import get_user_model
from ray.dashboard.modules.job.sdk import JobSubmissionClient
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Program, Job
from .ray import get_job_handler
from .schedule import save_program
from .serializers import JobSerializer
from .utils import build_env_variables

logger = logging.getLogger("gateway")


class ProgramViewSet(viewsets.ModelViewSet):  # pylint: disable=too-many-ancestors
    """
    Program ViewSet configuration using ModelViewSet.
    """

    BASE_NAME = "programs"

    @staticmethod
    def get_serializer_job_class():
        """
        This method returns Job serializer to be used in Program ViewSet.
        """

        return JobSerializer

    def get_serializer_class(self):
        return self.serializer_class

    def get_queryset(self):
        return Program.objects.all().filter(author=self.request.user)

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    @action(methods=["POST"], detail=False)
    def run(self, request):
        """Enqueues program for execution."""
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        program = save_program(serializer=serializer, request=request)
        job = Job(
            program=program,
            arguments=program.arguments,
            author=request.user,
            status=Job.QUEUED,
        )
        job.save()

        job.env_vars = json.dumps(build_env_variables(request, job, program))
        job.save()

        job_serializer = self.get_serializer_job_class()(job)
        return Response(job_serializer.data)


class JobViewSet(viewsets.ModelViewSet):  # pylint: disable=too-many-ancestors
    """
    Job ViewSet configuration using ModelViewSet.
    """

    BASE_NAME = "jobs"

    def get_serializer_class(self):
        return self.serializer_class

    def get_queryset(self):
        return Job.objects.all().filter(author=self.request.user).order_by("-created")

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    def retrieve(self, request, pk=None):  # pylint: disable=arguments-differ
        queryset = Job.objects.all()
        job: Job = get_object_or_404(queryset, pk=pk)
        serializer = self.get_serializer(job)
        return Response(serializer.data)

    @action(methods=["POST"], detail=True)
    def result(self, request, pk=None):  # pylint: disable=invalid-name,unused-argument
        """Save result of a job."""
        job = self.get_object()
        job.result = json.dumps(request.data.get("result"))
        job.save()
        serializer = self.get_serializer(job)
        return Response(serializer.data)

    @action(methods=["GET"], detail=True)
    def logs(self, request, pk=None):  # pylint: disable=invalid-name,unused-argument
        """Returns logs from job."""
        job = self.get_object()
        logs = job.logs
        if job.compute_resource:
            try:
                ray_client = JobSubmissionClient(job.compute_resource.host)
                logs = ray_client.get_job_logs(job.ray_job_id)
                job.logs = logs
                job.save()
            except Exception:  # pylint: disable=broad-exception-caught
                logger.warning("Ray cluster was not ready %s", job.compute_resource)
        return Response({"logs": logs})

    @action(methods=["POST"], detail=True)
    def stop(self, request, pk=None):  # pylint: disable=invalid-name,unused-argument
        """Stops job"""
        job = self.get_object()
        if not job.in_terminal_state():
            job.status = Job.STOPPED
            job.save()
        message = "Job has been stopped."
        if job.compute_resource:
            if job.compute_resource.active:
                job_handler = get_job_handler(job.compute_resource.host)
                if job_handler is not None:
                    was_running = job_handler.stop(job.ray_job_id)
                    if not was_running:
                        message = "Job was already not running."
                else:
                    logger.warning(
                        "Compute resource is not accessible %s", job.compute_resource
                    )
        return Response({"message": message})


class KeycloakLogin(SocialLoginView):
    """KeycloakLogin."""

    adapter_class = KeycloakOAuth2Adapter


class KeycloakUsersView(APIView):
    """KeycloakUsersView."""

    queryset = get_user_model().objects.all()
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        """Get application token.

        Request: /POST
        Body: {"username": ..., "password": ...}
        """
        keycloak_payload = {
            "grant_type": "password",
            "client_id": settings.SETTINGS_KEYCLOAK_CLIENT_ID,
            "client_secret": settings.SETTINGS_KEYCLOAK_CLIENT_SECRET,
            "scope": "openid",
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
