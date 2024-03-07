import ssl
import requests
import logging
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

logging.basicConfig(level=logging.DEBUG)

HOST = "127.0.0.1"
PORT = 8443


class ProxyRequestHandler(BaseHTTPRequestHandler):
    def handle_one_request(self):
        """Handle a single HTTP request.

        You normally don't need to override this method; see the class
        __doc__ string for information on how to handle specific HTTP
        commands such as GET and POST.

        """
        try:
            self.raw_requestline = self.rfile.readline(65537)
            if len(self.raw_requestline) > 65536:
                self.requestline = ""
                self.request_version = ""
                self.command = ""
                self.send_error(HTTPStatus.REQUEST_URI_TOO_LONG)
                return
            if not self.raw_requestline:
                self.close_connection = True
                return
            if not self.parse_request():
                # An error code has been sent, just exit
                return
            if self.command == "POST":
                self.do_POST()
            else:
                url = "https://" + self.headers["Host"] + self.path
                logging.debug("Passthrough none POST request: %s", url)
                resp = requests.request(self.command, url, headers=self.headers)
                self.send_response(resp.status_code)
                for header in resp.headers:
                    self.send_header(header, resp.headers[header])
                self.flush_headers()
                self.wfile.write(resp.content)
                logging.debug("response from backend: %s", resp.status_code)
            self.wfile.flush()  # actually send the response if not already done.
        except TimeoutError as e:
            # a read or a write timed out.  Discard this connection
            self.log_error("Request timed out: %r", e)
            self.close_connection = True
            return

    def do_POST(self):
        logging.debug("POST")
        url = "https://" + self.headers["Host"] + self.path
        logging.debug("Passthrough POST request: %s", url)
        content_length = int(self.headers["Content-Length"])
        data = self.rfile.read(content_length)
        job_request = self.path.find("/api/jobs") != -1
        if job_request:
            if "X-Qx-Client-Application" in self.headers:
                pos = self.headers["X-Qx-Client-Application"].find("middleware_job_id")
                if pos != -1:
                    id = self.headers["X-Qx-Client-Application"][
                        pos
                        + len("middleware_job_id/") : pos
                        + len("middleware_job_id/")
                        + 36
                    ]
                    logging.debug("Middleware Job ID: %s", id)

        resp = requests.request(self.command, url, headers=self.headers, data=data)
        self.send_response(resp.status_code)
        for header in resp.headers:
            self.send_header(header, resp.headers[header])
        self.flush_headers()
        self.wfile.write(resp.content)
        if job_request:
            jsondata = json.loads(resp.content.decode("utf-8"))
            logging.debug("job id: %s", jsondata["id"])

            token = "awesome_token"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            }
            r = requests.post(
                f"http://gateway:8000/api/v1/jobs/{id}/add_runtimejob/",
                headers=headers,
                json={"runtime_job": jsondata["id"]},
            )
            logging.debug("Gateway API Response: %s", r)
        logging.debug("response from backend: %s", resp.status_code)


if __name__ == "__main__":
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(
        certfile="/etc/ray/tls/tls.crt", keyfile="/etc/ray/tls/tls.key"
    )
    server_context.load_verify_locations(cafile="/etc/ca/tls/ca.crt")
    server_context.verify_mode = ssl.CERT_NONE

    httpd = ThreadingHTTPServer((HOST, PORT), ProxyRequestHandler)
    httpd.socket = server_context.wrap_socket(httpd.socket, server_hostname=HOST)

    print("forever")
    httpd.serve_forever()
