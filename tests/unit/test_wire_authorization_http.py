"""The complete wire matrix over localhost HTTP in the loopback tier."""

from http.client import HTTPConnection
import json
import threading

from ezllmrouter_server.http_server import BoundedHTTPServer
from tests.unit import test_wire_authorization as matrix


class LoopbackWireAuthorizationTests(matrix.WireAuthorizationTests):
    def setUp(self):
        super().setUp()
        server = BoundedHTTPServer(("127.0.0.1", 0), self.wire.handler)
        server.handler = self.wire.handler
        self.wire = server
        self.thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01))
        self.thread.start()
        self.addCleanup(self.stop_http)

    def stop_http(self):
        self.wire.shutdown()
        self.wire.server_close()
        self.thread.join(3)
        self.assertFalse(self.thread.is_alive())

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
            else None
        )
        headers = self.headers_for(row, actor, auth, version_headers)
        if method == "POST":
            headers += [("Content-Type", "application/json"), ("Content-Length", str(len(raw)))]
        connection = HTTPConnection("127.0.0.1", self.wire.server_port, timeout=5)
        try:
            connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            for key, value in headers:
                connection.putheader(key, value)
            connection.endheaders(raw)
            response = connection.getresponse()
            return response.status, response.headers, response.read()
        finally:
            connection.close()
