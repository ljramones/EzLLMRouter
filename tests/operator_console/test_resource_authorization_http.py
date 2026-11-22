"""Existing operator resource scenarios through localhost HTTP listeners."""

import threading

from ezllmrouter_server.http_server import BoundedHTTPServer
from tests.operator_console import test_authorization_matrix_http as transport
from tests.operator_console import test_resource_authorization as matrix


class LoopbackResourceAuthorizationTests(matrix.ResourceAuthorizationTests):
    def setUp(self):
        super().setUp()
        self.http = BoundedHTTPServer(("127.0.0.1", 0), self.server.handler)
        self.http.application = self.application
        self.addCleanup(self.http.server_close)
        self.thread = threading.Thread(target=lambda: self.http.serve_forever(poll_interval=0.01))
        self.thread.start()
        self.addCleanup(self.stop_http)

    def stop_http(self):
        self.http.shutdown()
        self.thread.join(3)
        self.assertFalse(self.thread.is_alive())

    exchange = transport.LoopbackAuthorizationMatrixTests.exchange
