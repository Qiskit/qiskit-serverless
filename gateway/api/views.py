"""
Django Rest framework views for api application:
    - QuantumFunction ViewSet
    - Job ViewSet
    - KeycloakUsers ApiView

Version views inherit from the different views.
"""

import json
import os.path
import shutil
import tarfile
import uuid
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


from .models import QuantumFunction, Job, ComputeResource
from .serializers import JobSerializer
from .utils import ray_job_status_to_model_job_status, try_json_loads


class QuantumFunctionViewSet(
    viewsets.ModelViewSet
):  # pylint: disable=too-many-ancestors
    """
    QuantumFunction ViewSet configuration using ModelViewSet.
    """

    BASE_NAME = "quantum-functions"

    @staticmethod
    def get_serializer_job_class():
        """
        This method returns Job serializer to be used in QuantumFunction ViewSet.
        """

        return JobSerializer

    def get_serializer_class(self):
        return self.serializer_class

    def get_queryset(self):
        return QuantumFunction.objects.all().filter(author=self.request.user)

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    @action(methods=["POST"], detail=False)
    def run(self, request):
        """Runs provided quantum function on compute resources."""

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            # create quantum_function
            quantum_function = QuantumFunction(**serializer.data)
            _, dependencies = try_json_loads(quantum_function.dependencies)
            _, arguments = try_json_loads(quantum_function.arguments)

            existing_quantum_functions = QuantumFunction.objects.filter(
                author=request.user, title__exact=quantum_function.title
            )
            if existing_quantum_functions.count() > 0:
                # take existing one
                existing_quantum_functions = existing_quantum_functions.first()
                existing_quantum_functions.arguments = quantum_function.arguments
                existing_quantum_functions.dependencies = quantum_function.dependencies
                quantum_function = existing_quantum_functions
            quantum_function.artifact = request.FILES.get("artifact")
            quantum_function.author = request.user
            quantum_function.save()

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
            with tarfile.open(quantum_function.artifact.path) as file:
                extract_folder = os.path.join(
                    settings.MEDIA_ROOT, "tmp", str(uuid.uuid4())
                )
                file.extractall(extract_folder)

            job = Job(
                quantum_function=quantum_function,
                author=request.user,
                compute_resource=compute_resource,
            )
            job.save()

            if arguments is not None:
                arg_list = []
                for key, value in arguments.items():
                    if isinstance(value, dict):
                        arg_list.append(f"--{key}='{json.dumps(value)}'")
                    else:
                        arg_list.append(f"--{key}={value}")
                arguments = " ".join(arg_list)
            else:
                arguments = ""
            entrypoint = f"python {quantum_function.entrypoint} {arguments}"

            ray_job_id = ray_client.submit_job(
                entrypoint=entrypoint,
                runtime_env={
                    "working_dir": extract_folder,
                    "env_vars": {
                        "ENV_JOB_GATEWAY_TOKEN": str(request.auth.token.decode()),
                        "ENV_JOB_GATEWAY_HOST": str(settings.SITE_HOST),
                        "ENV_JOB_ID_GATEWAY": str(job.id),
                    },
                    "pip": dependencies or [],
                },
            )
            job.ray_job_id = ray_job_id
            job.save()

            # remote temp data
            if os.path.exists(extract_folder):
                shutil.rmtree(extract_folder)

            job_serializer = self.get_serializer_job_class()(job)
            return Response(job_serializer.data)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class JobViewSet(viewsets.ModelViewSet):  # pylint: disable=too-many-ancestors
    """
    Job ViewSet configuration using ModelViewSet.
    """

    BASE_NAME = "jobs"

    def get_serializer_class(self):
        return self.serializer_class

    def get_queryset(self):
        return Job.objects.all().filter(author=self.request.user)

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    def retrieve(self, request, pk=None):  # pylint: disable=arguments-differ
        queryset = Job.objects.all()
        job: Job = get_object_or_404(queryset, pk=pk)
        serializer = self.get_serializer(job)
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
        job.save()
        serializer = self.get_serializer(job)
        return Response(serializer.data)

    @action(methods=["GET"], detail=True)
    def logs(self, request, pk=None):  # pylint: disable=invalid-name,unused-argument
        """Returns logs from job."""
        job = self.get_object()
        ray_client = JobSubmissionClient(job.compute_resource.host)
        return Response({"logs": ray_client.get_job_logs(job.ray_job_id)})


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
