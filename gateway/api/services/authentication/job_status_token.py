"""A short-lived signed token that lets the author of a job read its status without the API key."""

from django.contrib.auth import get_user_model
from django.core import signing
from rest_framework import authentication, exceptions

JOB_STATUS_TOKEN_HEADER = "X-Job-Status-Token"
_MAX_AGE_SECONDS = 300
_SALT = "qiskit-serverless.job-status-token"


def issue_job_status_token(user_id: int, job_id: str) -> str:
    """Sign the user id and the job id."""
    return signing.dumps({"u": user_id, "j": str(job_id)}, salt=_SALT)


class JobStatusTokenBackend(authentication.BaseAuthentication):
    """Authenticates only with X-Job-Status-Token, never with the API key. request.auth is the token's job id."""

    def authenticate(self, request):
        token = request.META.get("HTTP_X_JOB_STATUS_TOKEN")
        if not token:
            return None
        try:
            payload = signing.loads(token, salt=_SALT, max_age=_MAX_AGE_SECONDS)
        except signing.BadSignature:
            payload = None
        user = payload and get_user_model().objects.filter(id=payload["u"], is_active=True).first()
        if not user:
            raise exceptions.AuthenticationFailed("The job status token is not valid or has expired.")
        return user, payload["j"]

    def authenticate_header(self, request):
        return JOB_STATUS_TOKEN_HEADER
