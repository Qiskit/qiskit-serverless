"""proxy server"""
import json
import logging
import os
import time
import zlib
import requests
from werkzeug.datastructures import Headers

from flask import Flask, request, Response

app = Flask(__name__)

logging.basicConfig(level=os.environ.get("LOG_LEVEL", logging.DEBUG))

HOST = "127.0.0.1"
TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "30"))
PORT = int(os.environ.get("PROXY_PORT", "8443"))
MIDDLEWARE_JOB_ID_LENGTH = 36
MAX_URI_LENGTH = 8000  # https://www.rfc-editor.org/rfc/rfc9110#section-4.1

TEST_DST_PROTOCOL = "http"
TEST_GATEWAY_URL = "127.0.0.1:60000"
dst_protocol = os.environ.get("DST_PROTOCOL", TEST_DST_PROTOCOL)
gateway_url = os.environ.get("GATEWAY_URL", TEST_GATEWAY_URL)


def gzip_encode(content):
    """gzip encode"""
    gzip_compress = zlib.compressobj(9, zlib.DEFLATED, zlib.MAX_WBITS | 16)
    data = gzip_compress.compress(content) + gzip_compress.flush()
    return data


def handle_response(resp):
    """handle response."""
    status = resp.status_code
    if resp.content and len(resp.content) != 0:
        response = resp.content
        sanitized = response.replace('\n', '').replace('\r', '') 
        logging.debug("Recieved response content: %s", sanitized.decode("utf-8"))
        if (
            "content-encoding" in resp.headers
            and resp.headers["content-encoding"] == "gzip"
        ):
            response = gzip_encode(response)
    headers = Headers()
    for header in resp.headers:
        if header != "Transfer-Encoding":  # chunked encoding is not supported
            logging.debug("header: %s, %s", header, resp.headers[header])
            headers.add(header, resp.headers[header])
    if response and len(response) != 0:
        sanitized = response.replace('\n', '').replace('\r', '') 
        logging.debug("Sending response content: %s", sanitized)
    return Response(
        response=response, headers=headers, status=status, direct_passthrough=True
    )


@app.route("/<path:path>", methods=["GET"])
def do_get(path):  # pylint: disable=unused-argument
    """do_get"""
    url = request.url
    logging.debug("Passthrough none POST request: %s", url)
    resp = requests.request(
        request.method, request.url, headers=request.headers, timeout=TIMEOUT
    )
    return handle_response(resp)


@app.route("/<path:path>", methods=["POST"])
def do_post(path):  # pylint: disable=unused-argument
    """do_post"""
    logging.debug("POST")
    url = request.url
    logging.debug("Passthrough POST request: %s", url)
    data = request.get_data()
    job_request = request.path.find("/runtime/jobs") != -1
    middleware_job_id = None
    token = "awesome_token"
    if job_request:
        if "X-Qx-Client-Application" in request.headers:
            qiskit_header = request.headers["X-Qx-Client-Application"]
            logging.debug(
                "X-Qx-Client-Application: %s",
                qiskit_header,
            )
            pos = qiskit_header.find("middleware_job_id")
            if pos != -1:
                middleware_job_id = qiskit_header[
                    pos
                    + len("middleware_job_id/") : pos
                    + len("middleware_job_id/")
                    + MIDDLEWARE_JOB_ID_LENGTH
                ]
                logging.debug("Middleware Job ID: %s", middleware_job_id)
                token_begin = (
                    pos + len("middleware_job_id/") + MIDDLEWARE_JOB_ID_LENGTH + 1
                )
                token_end = qiskit_header.find("/", token_begin)
                token = qiskit_header[token_begin:token_end]
                sanitized = token.replace('\n', '').replace('\r', '')
                logging.debug("gateway token: %s", sanitized)

    resp = None
    retry = 5
    while resp is None and retry > 0:
        try:
            resp = requests.request(
                request.method, url, headers=request.headers, data=data, timeout=TIMEOUT
            )
        except:  # pylint: disable=bare-except
            logging.debug("request error retrying")
            time.sleep(3)
            retry -= 1

    if job_request and middleware_job_id:
        jsondata = json.loads(resp.content.decode("utf-8"))
        sanitized = jsondata.replace('\n', '').replace('\r', '')
        logging.debug("job id: %s", sanitized["id"])

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        gateway_resp = requests.post(
            f"http://{gateway_url}/api/v1/jobs/{middleware_job_id}/add_runtimejob/",
            headers=headers,
            json={"runtime_job": jsondata["id"]},
            timeout=TIMEOUT,
        )
        sanitized = gateway_resp.replace('\n', '').replace('\r', '')
        logging.debug("Gateway API Response: %s", sanitized)
    logging.debug("response from backend: %s", resp.status_code)
    return handle_response(resp)
