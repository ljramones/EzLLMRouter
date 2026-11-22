"""The complete wire authorization matrix through real HTTP socket parsing."""

from http.client import HTTPResponse
import json

from tests.operator_console.test_authorization_matrix_sockets import ResponseSocket
from tests.unit import test_http_structure as framing
from tests.unit import test_wire_authorization as matrix


class SocketWireAuthorizationTests(matrix.WireAuthorizationTests):
    def exchange(
        self,
        row,
        actor="work_owner",
        *,
        auth=None,
        version_headers=None,
        body=None,
        path=None,
        method=None,
    ):
        request_path, request_body = self.request_for(row, actor)
        method, path = method or row["method"], path or request_path
        raw = (
            json.dumps(request_body if body is None else body, separators=(",", ":")).encode()
            if method == "POST"
            else b""
        )
        headers = self.headers_for(row, actor, auth, version_headers)
        if method == "POST":
            headers += [("Content-Type", "application/json"), ("Content-Length", str(len(raw)))]
        request = (
            method
            + " "
            + path
            + " HTTP/1.1\r\n"
            + "".join(key + ": " + value + "\r\n" for key, value in headers)
            + "\r\n"
        ).encode() + raw
        reply = framing.HTTPFramingTests.exchange(self, self.wire, request)
        response = HTTPResponse(ResponseSocket(reply), method=method)
        response.begin()
        return response.status, response.headers, response.read()
