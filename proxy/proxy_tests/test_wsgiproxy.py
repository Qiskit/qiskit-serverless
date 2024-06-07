"""Tests wsgiproxy"""
import time
from proxy.wsgiproxy import app
import threading
from http.server import HTTPServer
import unittest
import operator
import urllib
from http.server import BaseHTTPRequestHandler


def client(app):
    return app.test_client()


class MockServerThread(threading.Thread):
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
        mock.thread = MockServerThread(self, mock.mock_handler)
        mock.thread.start()
        time.sleep(3)

    def tearDown(self, mock):
        """tearDown"""
        mock.thread.stop()
        mock.thread = None


class TestHTTPServer(unittest.TestCase):
    """TestHTTPServer."""

    mock = None

    def setUp(self):
        """setUp"""
        self.mock = MockServer()
        BaseTestCase.setUp(self, self.mock)
        print("setup")

    def test_none_post(self):
        """test none post"""
        res = client(app).get("/api", headers={"HOST": "127.0.0.1:60000"})
        print(res)
        self.assertEqual(res.status, "200 OK")

    def test_post(self):
        """test post"""
        data = urllib.parse.urlencode(
            {"@number": 12524, "@type": "issue", "@action": "show"}
        )
        res = client(app).post("/api", headers={"HOST": "127.0.0.1:60000"}, data=data)
        self.assertEqual(res.status, "200 OK")

    def test_job_request(self):
        """test job request"""
        data = urllib.parse.urlencode(
            {"@number": 12524, "@type": "issue", "@action": "show"}
        )
        res = client(app).post(
            "/runtime/jobs",
            headers={
                "HOST": "127.0.0.1:60000",
                "X-Qx-Client-Application": "other:middleware_job_id/0123456789012345678901234567890123456789",
            },
            data=data,
        )
        self.assertEqual(res.status, "200 OK")

    def tearDown(self):
        """tearDown"""
        print("tearDown")
        BaseTestCase.tearDown(self, self.mock)


if __name__ == "__main__":
    app = app
    app.config.update(
        {
            "TESTING": True,
        }
    )
    unittest.main()
