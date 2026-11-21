"""Real HTTP parsing over local socket pairs, available in the offline gate."""

from http.client import HTTPResponse
import io

from tests.operator_console.test_authorization_matrix import AuthorizationMatrixTests
from tests.unit.test_http_structure import HTTPFramingTests


class ResponseSocket:
    def __init__(self, raw):
        self.raw = raw

    def makefile(self, *_args):
        return io.BytesIO(self.raw)


class SocketPairAuthorizationMatrixTests(AuthorizationMatrixTests):
    def test_authenticated_socket_response_is_not_cacheable(self):
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
        body = b"{}" if method != "GET" else b""
        if body:
            headers.update({"Content-Type": "application/json", "Content-Length": "2"})
        raw = (
            method
            + " "
            + path
            + " HTTP/1.1\r\n"
            + "".join(name + ": " + value + "\r\n" for name, value in headers.items())
            + "\r\n"
        ).encode() + body
        reply = HTTPFramingTests.exchange(self, self.server, raw)
        response = HTTPResponse(ResponseSocket(reply))
        response.begin()
        return response.status, response.headers, response.read()
