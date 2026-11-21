"""The same independent route matrix over real localhost HTTP connections."""

from http.client import HTTPConnection
import threading

from ezllmrouter_server.http_server import BoundedHTTPServer
from tests.operator_console.test_authorization_matrix import AuthorizationMatrixTests


class LoopbackAuthorizationMatrixTests(AuthorizationMatrixTests):
    def setUp(self):
        super().setUp()
        self.http = BoundedHTTPServer(("127.0.0.1", 0), self.server.handler)
        self.http.application = self.server.application
        self.addCleanup(self.http.server_close)
        self.thread = threading.Thread(target=lambda: self.http.serve_forever(poll_interval=0.01))
        self.thread.start()
        self.addCleanup(self.stop_http)

    def stop_http(self):
        self.http.shutdown()
        self.thread.join(3)
        self.assertFalse(self.thread.is_alive())

    def test_authenticated_http_response_is_not_cacheable(self):
        self.cookie, self.csrf = self.ordinary
        status, headers, _ = self.exchange("GET", "/operator/v1/session")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store, max-age=0")

    def exchange(self, method, path, *, host=None, origin=None, csrf=True):
        headers = {"Host": host or "127.0.0.1:48761", "Origin": origin or "http://127.0.0.1:48761"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        if csrf and self.csrf:
            headers["X-EzLLMRouter-CSRF"] = self.csrf
        body = b"{}" if method != "GET" else None
        if body is not None:
            headers["Content-Type"] = "application/json"
        connection = HTTPConnection("127.0.0.1", self.http.server_port, timeout=3)
        try:
            connection.request(method, path, body, headers)
            response = connection.getresponse()
            return response.status, response.headers, response.read()
        finally:
            connection.close()
