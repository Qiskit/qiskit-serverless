"""Tests HTTPServer"""
import threading
from http.server import HTTPServer
import http, http.client, urllib.parse
import unittest
import operator
from proxy.httpserver import ProxyRequestHandler
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler


class TestServerThread(threading.Thread):
    """TestServerThread"""

    def __init__(self, test_object, request_handler):
        """init"""
        threading.Thread.__init__(self)
        self.request_handler = request_handler
        self.test_object = test_object

    def run(self):
        """run"""
        self.server = HTTPServer(("localhost", 0), self.request_handler)
        self.test_object.HOST, self.test_object.PORT = self.server.socket.getsockname()
        self.test_object.server_started.set()
        self.test_object = None
        try:
            self.server.serve_forever(0.05)
        finally:
            self.server.server_close()

    def stop(self):
        """stop"""
        self.server.shutdown()
        self.join()


class TestMockServerThread(threading.Thread):
    """TestMockserverThread"""

    def __init__(self, test_object, request_handler):
        """init"""
        threading.Thread.__init__(self)
        self.request_handler = request_handler
        self.test_object = test_object

    def run(self):
        """run"""
        self.mock_server = HTTPServer(("localhost", 60000), self.request_handler)
        self.test_object = None
        try:
            self.mock_server.serve_forever(0.05)
        finally:
            self.mock_server.server_close()

    def stop(self):
        """stop"""
        self.mock_server.shutdown()
        self.join()


class MockServer(unittest.TestCase):
    """MockServer"""

    class mock_handler(BaseHTTPRequestHandler):
        def do_GET(self):
            """do_GET"""
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Hello, world from GET!")

        def do_POST(self):
            """do_POST"""
            if self.path == "/runtime/jobs":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"test": "json", "id": "job_id"}')
            elif operator.contains(self.path, "/api/v1/jobs"):
                data = self.rfile.read(25)
                print(data)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Hello, world from Gateway!")
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Hello, world from POST!")


class BaseTestCase(unittest.TestCase):
    """BaseTestCase"""

    def setUp(self, mock):
        """setUp"""
        self.server_started = threading.Event()
        self.thread = TestServerThread(self, self.request_handler)
        self.thread.start()
        mock.thread = TestMockServerThread(self, mock.mock_handler)
        mock.thread.start()
        self.server_started.wait()

    def tearDown(self, mock):
        """tearDown"""
        self.thread.stop()
        self.thread = None
        mock.thread.stop()
        mock.thread = None

    def request(self, uri, method="GET", body=None, headers={}):
        """request"""
        self.connection = http.client.HTTPConnection(self.HOST, self.PORT)
        self.connection.request(method, uri, body, headers)
        return self.connection.getresponse()


class TestHTTPServer(unittest.TestCase):
    """TestHTTPServer."""

    mock = None

    def setUp(self):
        """setUp"""
        self.mock = MockServer()
        BaseTestCase.setUp(self, self.mock)
        self.con = http.client.HTTPConnection(self.HOST, self.PORT)
        self.con.connect()

    class request_handler(ProxyRequestHandler):
        """request handler"""

        None

    def test_none_post(self):
        """test none post"""
        self.con.request("GET", "/", headers={"HOST": "127.0.0.1:60000"})
        res = self.con.getresponse()
        self.assertEqual(res.getcode(), 200)

    def test_post(self):
        """test post"""
        params = urllib.parse.urlencode(
            {"@number": 12524, "@type": "issue", "@action": "show"}
        )
        self.con.request("POST", "/", params, headers={"HOST": "127.0.0.1:60000"})
        res = self.con.getresponse()
        self.assertEqual(res.getcode(), 200)

    def test_job_request(self):
        """test job request"""
        params = urllib.parse.urlencode(
            {"@number": 12524, "@type": "issue", "@action": "show"}
        )
        self.con.request(
            "POST",
            "/runtime/jobs",
            params,
            headers={
                "HOST": "127.0.0.1:60000",
                "X-Qx-Client-Application": "other:middleware_job_id/0123456789012345678901234567890123456789",
            },
        )
        res = self.con.getresponse()
        self.assertEqual(res.getcode(), 200)

    def tearDown(self):
        """tearDown"""
        BaseTestCase.tearDown(self, self.mock)


if __name__ == "__main__":
    unittest.main()
