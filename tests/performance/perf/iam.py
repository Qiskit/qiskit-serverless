"""An IBM Cloud IAM token from IBM_CLOUD_API_KEY, for the Sysdig and Code Engine APIs."""

import json
import os
import urllib.parse
import urllib.request

IAM_URL = "https://iam.cloud.ibm.com/identity/token"


def api_key() -> str | None:
    """IBM_CLOUD_API_KEY, a production IBM Cloud key."""
    return os.environ.get("IBM_CLOUD_API_KEY")


def token(key: str) -> str:
    """A bearer token for the key."""
    data = urllib.parse.urlencode({"grant_type": "urn:ibm:params:oauth:grant-type:apikey", "apikey": key}).encode()
    request = urllib.request.Request(IAM_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)["access_token"]
