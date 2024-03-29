"""proxy server"""
from http import HTTPStatus
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import json
import logging
import os
import ssl
import time
import zlib
import requests

logging.basicConfig(level=os.environ.get("LOG_LEVEL", logging.DEBUG))

HOST = "127.0.0.1"
TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "30"))
PORT = int(os.environ.get("PROXY_PORT", "8443"))
MIDDLEWARE_JOB_ID_LENGTH = 36

TEST_DST_PROTOCOL = "http"
TEST_GATEWAY_URL = "127.0.0.1:60000"
dst_protocol = os.environ.get("DST_PROTOCOL", TEST_DST_PROTOCOL)
gateway_url = os.environ.get("GATEWAY_URL", TEST_GATEWAY_URL)


class ProxyRequestHandler(BaseHTTPRequestHandler):
    """Proxy Request Handler."""

    def gzip_encode(self, content):
        """gzip encode"""
        gzip_compress = zlib.compressobj(9, zlib.DEFLATED, zlib.MAX_WBITS | 16)
        data = gzip_compress.compress(content) + gzip_compress.flush()
        return data

    def chunked_transfer(self, content):
        """chunked transfer"""
        content = (
            bytes(f"{len(content):x}", "utf-8")
            + b"\x0d\x0a"
            + content
            + b"\x0d\x0a0\x0d\x0a\x0d\x0a"
        )
        return content

    def handle_response(self, resp):
        """handle response."""
        self.send_response(resp.status_code)
        if resp.content and len(resp.content) != 0:
            content = resp.content
            logging.debug("Recieved response content: %s", content.decode("utf-8"))
            if (
                "content-encoding" in resp.headers
                and resp.headers["content-encoding"] == "gzip"
            ):
                content = self.gzip_encode(content)
            if (
                "Transfer-Encoding" in resp.headers
                and resp.headers["Transfer-Encoding"] == "chunked"
            ):
                content = self.chunked_transfer(content)
        for header in resp.headers:
            self.send_header(header, resp.headers[header])
            logging.debug("header: %s, %s", header, resp.headers[header])
        self.end_headers()
        if resp.content and len(resp.content) != 0:
            self.wfile.write(content)
            logging.debug("Sending response content: %s", content)

    def handle_one_request(self):
        """Handle a single HTTP request."""

        try:
            logging.debug("New request")
            self.raw_requestline = (  # pylint: disable=attribute-defined-outside-init
                self.rfile.readline(65537)
            )
            logging.debug("New request: %s", self.raw_requestline)
            if len(self.raw_requestline) > 65536:
                self.requestline = ""  # pylint: disable=attribute-defined-outside-init
                self.request_version = (  # pylint: disable=attribute-defined-outside-init
                    ""
                )
                self.command = ""  # pylint: disable=attribute-defined-outside-init
                self.send_error(HTTPStatus.REQUEST_URI_TOO_LONG)
                return
            if not self.raw_requestline:
                self.close_connection = (  # pylint: disable=attribute-defined-outside-init
                    True
                )
                return
            if not self.parse_request():
                # An error code has been sent, just exit
                return
            if self.command == "POST":
                self.do_POST()
            else:
                url = f"{dst_protocol}://" + self.headers["Host"] + self.path
                logging.debug("Passthrough none POST request: %s", url)
                resp = requests.request(
                    self.command, url, headers=self.headers, timeout=TIMEOUT
                )
                self.handle_response(resp)
            self.wfile.flush()  # actually send the response if not already done.
        except TimeoutError as e:
            # a read or a write timed out.  Discard this connection
            self.log_error("Request timed out: %r", e)
            self.close_connection = (  # pylint: disable=attribute-defined-outside-init
                True
            )
            return

    def do_POST(self):  # pylint: disable=invalid-name
        """do POST"""
        logging.debug("POST")
        url = f"{dst_protocol}://" + self.headers["Host"] + self.path
        logging.debug("Passthrough POST request: %s", url)
        content_length = int(self.headers["Content-Length"])
        data = self.rfile.read(content_length)
        job_request = self.path.find("/runtime/jobs") != -1
        middleware_job_id = None
        if job_request:
            if "X-Qx-Client-Application" in self.headers:
                logging.debug(
                    "X-Qx-Client-Application: %s",
                    self.headers["X-Qx-Client-Application"],
                )
                pos = self.headers["X-Qx-Client-Application"].find("middleware_job_id")
                if pos != -1:
                    middleware_job_id = self.headers["X-Qx-Client-Application"][
                        pos
                        + len("middleware_job_id/") : pos
                        + len("middleware_job_id/")
                        + MIDDLEWARE_JOB_ID_LENGTH
                    ]
                    logging.debug("Middleware Job ID: %s", middleware_job_id)

        resp = None
        retry = 5
        while resp is None and retry > 0:
            try:
                resp = requests.request(
                    self.command, url, headers=self.headers, data=data, timeout=TIMEOUT
                )
            except:  # pylint: disable=bare-except
                logging.debug("request error retrying")
                time.sleep(3)
                retry -= 1

        self.handle_response(resp)
        self.wfile.flush()  # actually send the response if not already done.
        if job_request and middleware_job_id:
            jsondata = json.loads(resp.content.decode("utf-8"))
            logging.debug("job id: %s", jsondata["id"])

            token = "awesome_token"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            }
            r = requests.post(
                f"http://{gateway_url}/api/v1/jobs/{middleware_job_id}/add_runtimejob/",
                headers=headers,
                json={"runtime_job": jsondata["id"]},
                timeout=TIMEOUT,
            )
            logging.debug("Gateway API Response: %s", r)
        logging.debug("response from backend: %s", resp.status_code)


if __name__ == "__main__":
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(
        certfile="/etc/ray/tls/tls.crt", keyfile="/etc/ray/tls/tls.key"
    )
    server_context.load_verify_locations(cafile="/etc/ca/tls/ca.crt")

    httpd = ThreadingHTTPServer((HOST, PORT), ProxyRequestHandler)
    httpd.socket = server_context.wrap_socket(httpd.socket, server_hostname=HOST)

    logging.info("Running proxy server...")
    httpd.serve_forever()
