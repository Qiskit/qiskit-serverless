"""A short-lived signed token that lets the author of a job read its status without the API key."""

import logging
from dataclasses import dataclass
from typing import Optional

from django.contrib.auth import get_user_model
from django.core import signing
from rest_framework import authentication, exceptions

logger = logging.getLogger("api.authentication.job_status_token")

JOB_STATUS_TOKEN_HEADER = "X-Job-Status-Token"
JOB_STATUS_TOKEN_MAX_AGE_SECONDS = 300
_SALT = "qiskit-serverless.job-status-token"


@dataclass(frozen=True)
class JobStatusTokenAuth:
    """The job the token was issued for, set as request.auth by JobStatusTokenBackend."""

    job_id: str


def issue_job_status_token(user_id: int, job_id: str) -> str:
    """Sign the user id and the job id."""
    return signing.dumps({"u": user_id, "j": str(job_id)}, salt=_SALT, compress=True)


def read_job_status_token(token: str) -> Optional[dict]:
    """The payload of a valid token younger than 5 minutes, or None."""
    try:
        return signing.loads(token, salt=_SALT, max_age=JOB_STATUS_TOKEN_MAX_AGE_SECONDS)
    except signing.BadSignature:
        return None


class JobStatusTokenBackend(authentication.BaseAuthentication):
    """Authenticates only with X-Job-Status-Token, never with the API key, and never calls IBM Cloud."""

    def authenticate(self, request):
        token = request.META.get("HTTP_X_JOB_STATUS_TOKEN")
        if not token:
            return None
        payload = read_job_status_token(token)
        if payload is None:
            raise exceptions.AuthenticationFailed("The job status token is not valid or has expired.")
        user = get_user_model().objects.filter(id=payload["u"], is_active=True).first()
        if user is None:
            raise exceptions.AuthenticationFailed("The job status token is not valid or has expired.")
        return user, JobStatusTokenAuth(job_id=payload["j"])

    def authenticate_header(self, request):
        return JOB_STATUS_TOKEN_HEADER
