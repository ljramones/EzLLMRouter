"""Real body parsers and bounded response readers at their declared byte ceilings."""

import json
from unittest.mock import Mock

import httpx

from ezllmrouter_client import _http
from tests.unit import test_generated_http_framing as framing
import unittest


class RequestBodyLimitTests(framing.AuthenticatedFramingTests):
    def test_declared_operator_wire_and_successor_body_ceilings_dispatch_only_at_the_limit(self):
        targets, _ = self.targets()
        wire = targets[1][1]
        coordinator = wire.handler.keywords["application"].coordinator
        successor = Mock()
        successor.submit.return_value = (200, {"contract_version": "0.3"})
        coordinator.successor = successor
        for kind, server, path, limit, dispatch, _reader in targets:
            for extra in (0, 1):
                body = self.payload(kind, extra)
                raw = json.dumps(body).encode()
                raw += b" " * (limit + extra - len(raw))
                dispatch.reset_mock()
                with self.subTest(kind=kind, extra=extra):
                    reply = self.exchange(
                        server,
                        self.request_bytes(
                            path,
                            f"Content-Length: {len(raw)}\r\n".encode(),
                            raw if not extra else b"",
                            close=True,
                        ),
                    )
                    self.assertEqual(
                        int(reply.split(b" ", 2)[1]),
                        (400 if kind == "operator" else 413)
                        if extra
                        else 201
                        if kind == "operator"
                        else 200,
                    )
                    self.assertEqual(dispatch.call_count, 0 if extra else 1)
        for extra in (0, 1):
            raw = b'{"contract_version":"0.3"}'
            raw += b" " * (262144 + extra - len(raw))
            request = self.request_bytes(
                "/v1/submissions",
                f"Content-Length: {len(raw)}\r\n".encode(),
                raw if not extra else b"",
                close=True,
            ).replace(b"Contract-Version: 0.2", b"Contract-Version: 0.3")
            successor.submit.reset_mock()
            with self.subTest(kind="wire-0.3", extra=extra):
                reply = self.exchange(wire, request)
                self.assertEqual(int(reply.split(b" ", 2)[1]), 413 if extra else 200)
                self.assertEqual(successor.submit.call_count, 0 if extra else 1)


class ResponseLimitTests(unittest.TestCase):
    def test_one_and_sixteen_megabyte_readers_accept_the_limit_and_close_on_one_more(self):
        for limit in (1048576, 16777216):
            for extra in (0, 1):
                reads, closed, calls = [], [], []

                class Stream(httpx.SyncByteStream):
                    def __iter__(self, limit=limit, extra=extra, reads=reads):
                        remaining = limit + extra
                        while remaining:
                            count = min(65536, remaining)
                            reads.append(count)
                            yield b" " * count
                            remaining -= count

                    def close(self, closed=closed):
                        closed.append(True)

                def respond(request, calls=calls, Stream=Stream):
                    calls.append(request)
                    return httpx.Response(200, stream=Stream())

                with (
                    self.subTest(limit=limit, extra=extra),
                    httpx.Client(transport=httpx.MockTransport(respond)) as client,
                ):
                    if extra:
                        with self.assertRaises(_http.ResponseReadError) as error:
                            _http.bounded_request(
                                client, "GET", "http://synthetic.invalid", headers={}, limit=limit
                            )
                        self.assertEqual(error.exception.status_code, 200)
                    else:
                        response = _http.bounded_request(
                            client, "GET", "http://synthetic.invalid", headers={}, limit=limit
                        )
                        self.assertEqual(len(response.content), limit)
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(closed, [True])
                    self.assertEqual(sum(reads), limit + extra)
