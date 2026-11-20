"""Bounded streaming, recovery correlation and client defaults without sockets."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

import httpx

from ezllmrouter_client import (
    EzLLMRouterClient,
    EzLLMRouterError,
    IntegrationClient,
    IntegrationClientError,
)
from ezllmrouter_client import _successor_validation as validation
from ezllmrouter_client._http import ResponseReadError, bounded_request
from tests.client_parity import test_python_client as legacy
from tests.development_slice import test_retrieval_client as successor

ROOT = Path(__file__).resolve().parents[2]
VECTORS = json.loads(
    (ROOT / "tests/fixtures/contracts/dev12-successor-01/vectors.json").read_text()
)


class RecordingStream(httpx.SyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.reads = 0
        self.closed = False

    def __iter__(self):
        for chunk in self.chunks:
            self.reads += 1
            yield chunk

    def close(self):
        self.closed = True


class ClientTransportTests(unittest.TestCase):
    def invoke(self, kind, stream, *, extra_headers=None):
        calls = []

        def respond(request):
            calls.append(request)
            headers = {
                "EzLLMRouter-Contract-Version": "0.3" if kind == "successor" else "0.2",
                "EzLLMRouter-Integration-Version": "1",
                **(extra_headers or {}),
            }
            return httpx.Response(200, headers=headers, stream=stream)

        transport = httpx.Client(transport=httpx.MockTransport(respond), trust_env=False)
        self.addCleanup(transport.close)
        client_type = IntegrationClient if kind == "integration" else EzLLMRouterClient
        client = client_type(
            "http://synthetic.invalid", "synthetic-client-token", transport=transport
        )
        self.addCleanup(client.close)
        action = {
            "wire": lambda: client.submit(legacy.EXAMPLES["submit_text"]),
            "successor": lambda: client.submit_rerank(deepcopy(successor.REQUEST)),
            "integration": lambda: client.report("dataset.synthetic"),
            "attribution": lambda: client.get_run("run.synthetic"),
        }[kind]
        return action, calls

    def test_compression_is_rejected_before_reading_every_protocol(self):
        for kind in ("wire", "successor", "integration", "attribution"):
            with self.subTest(kind=kind):
                stream = RecordingStream([b"compressed content must not be decoded"])
                action, calls = self.invoke(
                    kind, stream, extra_headers={"Content-Encoding": "gzip"}
                )
                with self.assertRaises((EzLLMRouterError, IntegrationClientError)) as error:
                    action()
                self.assertEqual(error.exception.code, "TRANSPORT_OUTCOME_UNKNOWN")
                self.assertEqual(error.exception.http_status, 200)
                self.assertEqual(error.exception.retry_guidance, "query_first")
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0].headers["Accept-Encoding"], "identity")
                self.assertEqual(stream.reads, 0)
                self.assertTrue(stream.closed)

    def test_declared_oversize_response_is_closed_without_reading(self):
        for kind in ("wire", "successor", "integration", "attribution"):
            with self.subTest(kind=kind):
                stream = RecordingStream([b"unused"])
                action, calls = self.invoke(
                    kind, stream, extra_headers={"Content-Length": str(32 * 1024 * 1024)}
                )
                with self.assertRaises((EzLLMRouterError, IntegrationClientError)):
                    action()
                self.assertEqual(stream.reads, 0)
                self.assertTrue(stream.closed)
                self.assertEqual(len(calls), 1)

    def test_unknown_length_stream_stops_at_the_limit_and_never_retries(self):
        stream = RecordingStream([b"x" * 65536] * 100)
        action, calls = self.invoke("wire", stream)
        with self.assertRaises(EzLLMRouterError) as error:
            action()
        self.assertEqual(error.exception.code, "TRANSPORT_OUTCOME_UNKNOWN")
        self.assertLessEqual(stream.reads, 17)
        self.assertTrue(stream.closed)
        self.assertEqual(len(calls), 1)

    def test_small_limit_handles_chunk_boundaries_and_length_mismatches(self):
        for raw, declared, accepted in (
            ([b"123", b"4567"], "7", True),
            ([b"123", b"4567"], "6", False),
            ([b"123", b"456789012"], None, False),
        ):
            with self.subTest(declared=declared, accepted=accepted):
                stream = RecordingStream(raw)
                with httpx.Client(
                    transport=httpx.MockTransport(
                        lambda _, *, declared=declared, stream=stream: httpx.Response(
                            200,
                            headers={"Content-Length": declared} if declared else {},
                            stream=stream,
                        )
                    )
                ) as transport:
                    if accepted:
                        response = bounded_request(
                            transport, "GET", "http://synthetic.invalid", headers={}, limit=10
                        )
                        self.assertEqual(response.content, b"1234567")
                    else:
                        with self.assertRaises(ResponseReadError):
                            bounded_request(
                                transport, "GET", "http://synthetic.invalid", headers={}, limit=10
                            )
                self.assertTrue(stream.closed)

    def test_body_timeout_preserves_status_and_closes_the_stream(self):
        class TimedOut(RecordingStream):
            def __iter__(self):
                self.reads += 1
                raise httpx.ReadTimeout("simulated body timeout")
                yield b"unreachable"

        stream = TimedOut([])
        action, calls = self.invoke("wire", stream)
        with self.assertRaises(EzLLMRouterError) as error:
            action()
        self.assertEqual(
            (error.exception.code, error.exception.http_status), ("TRANSPORT_OUTCOME_UNKNOWN", 200)
        )
        self.assertTrue(stream.closed)
        self.assertEqual(len(calls), 1)

    def test_default_phase_timeouts_allow_the_server_wait_and_can_be_overridden(self):
        for client_type in (EzLLMRouterClient, IntegrationClient):
            with (
                self.subTest(client=client_type.__name__),
                client_type("http://synthetic.invalid", "token") as client,
            ):
                transport = client._transport
                timeout = transport.timeout
                self.assertEqual(
                    (timeout.connect, timeout.read, timeout.write, timeout.pool), (10, 35, 30, 10)
                )
                self.assertFalse(transport.follow_redirects)
                self.assertFalse(transport.trust_env)
            with client_type(
                "http://synthetic.invalid", "token", timeout=httpx.Timeout(2, read=40)
            ) as client:
                transport = client._transport
                self.assertEqual(transport.timeout.connect, 2)
                self.assertEqual(transport.timeout.read, 40)

    def test_integration_replies_share_safe_integer_depth_and_scalar_validation(self):
        for content in (
            b'{"integration_version":"1","value":9007199254740992}',
            b'{"integration_version":"1","value":"\\ud800"}',
            b'{"integration_version":"1","value":' + b"[" * 40 + b"0" + b"]" * 40 + b"}",
        ):
            with self.subTest(prefix=content[:40]):
                action, calls = self.invoke("integration", RecordingStream([content]))
                with self.assertRaises(IntegrationClientError) as error:
                    action()
                self.assertEqual(error.exception.code, "TRANSPORT_OUTCOME_UNKNOWN")
                self.assertEqual(len(calls), 1)

    def test_invalid_snapshot_input_is_rejected_without_transport(self):
        transport = legacy.Transport()
        with IntegrationClient(
            "http://synthetic.invalid", "token", transport=transport, version="2"
        ) as client:
            for value in (None, [], "bad", 123):
                with self.subTest(value=value), self.assertRaises(TypeError):
                    client.submit_snapshot(value)
        self.assertEqual(transport.calls, [])


class RecoveryHandleTests(unittest.TestCase):
    def test_foreign_and_malformed_handles_are_never_attached_to_errors(self):
        for wire in ("0.2", "0.3"):
            for malformed in (False, True):
                with self.subTest(wire=wire, malformed=malformed):
                    reply = deepcopy(
                        legacy.EXAMPLES["reply_delivered"] if wire == "0.2" else successor.COMPLETED
                    )
                    if malformed:
                        reply["handle"] = ["not a handle"]
                    else:
                        reply["handle"]["work_key"]["task_id"] = "task.foreign"
                    transport = legacy.Transport(legacy.Response(reply, version=wire))
                    with EzLLMRouterClient(
                        "http://synthetic.invalid", "token", transport=transport
                    ) as client:
                        with self.assertRaises(EzLLMRouterError) as error:
                            if wire == "0.2":
                                client.submit(legacy.EXAMPLES["submit_text"])
                            else:
                                client.submit_rerank(deepcopy(successor.REQUEST))
                    self.assertIsNone(error.exception.handle)
                    self.assertIsNone(error.exception.work_key)
                    self.assertEqual(len(transport.calls), 1)

    def test_foreign_submission_id_is_rejected_for_both_status_protocols(self):
        for wire in ("0.2", "0.3"):
            reply = deepcopy(
                legacy.EXAMPLES["status_present"] if wire == "0.2" else successor.STATUS
            )
            transport = legacy.Transport(legacy.Response(reply, version=wire))
            with (
                self.subTest(wire=wire),
                EzLLMRouterClient(
                    "http://synthetic.invalid", "token", transport=transport
                ) as client,
            ):
                with self.assertRaises(EzLLMRouterError) as error:
                    client.get_status(
                        {"submission_id": "submission.foreign"}, contract_version=wire
                    )
                self.assertIsNone(error.exception.handle)
                self.assertIsNone(error.exception.work_key)

    def test_verified_failure_keeps_its_matching_recovery_handle(self):
        for wire, reply in (
            ("0.2", legacy.EXAMPLES["reply_failed_fdc"]),
            ("0.3", successor.FAILED),
        ):
            transport = legacy.Transport(legacy.Response(reply, status=409, version=wire))
            with (
                self.subTest(wire=wire),
                EzLLMRouterClient(
                    "http://synthetic.invalid", "token", transport=transport
                ) as client,
            ):
                with self.assertRaises(EzLLMRouterError) as error:
                    if wire == "0.2":
                        client.submit(legacy.EXAMPLES["submit_text"])
                    else:
                        client.submit_rerank(deepcopy(successor.REQUEST))
                self.assertEqual(error.exception.handle, reply["handle"])
                self.assertEqual(error.exception.work_key, reply["handle"]["work_key"])


class SuccessorResultTests(unittest.TestCase):
    def large_embedding(self):
        example = next(row for row in VECTORS["examples"] if row["id"] == "DIRECT_DOCUMENT")
        request = deepcopy(example["request"])
        request["requested_configuration_ref"] = "cfg.newly.registered.embedding"
        request["input"]["profile"].update(
            profile_id="space.new", model_ref="model.new", dimensions=2048
        )
        request["input"]["items"] = [
            {"item_id": "item." + str(i), "text": "synthetic"} for i in range(25)
        ]
        result = deepcopy(
            next(
                row["value"]
                for row in VECTORS["result_examples"]
                if row["id"] == "EMBEDDING_RESULT"
            )
        )
        result.update(
            attempt_id=successor.COMPLETED["attempt_id"],
            dimensions=2048,
            profile_id="space.new",
            model_ref="model.new",
        )
        result["vectors"] = [
            {"item_id": item["item_id"], "input_index": i, "values": ["0.1234567890123456"] * 2048}
            for i, item in enumerate(request["input"]["items"])
        ]
        return request, result

    def test_schema_sized_embedding_can_be_submitted_and_recovered(self):
        request, result = self.large_embedding()
        reply = deepcopy(successor.COMPLETED)
        reply["handle"]["work_key"].update(request["work_selector"])
        reply["result"] = result
        raw = json.dumps(reply, separators=(",", ":")).encode()
        self.assertGreater(len(raw), 65536)
        stream = RecordingStream(raw[index : index + 65536] for index in range(0, len(raw), 65536))
        with httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, headers={"EzLLMRouter-Contract-Version": "0.3"}, stream=stream
                )
            )
        ) as transport:
            with EzLLMRouterClient(
                "http://synthetic.invalid", "token", transport=transport
            ) as client:
                self.assertEqual(client.submit_embedding(request)["result"]["dimensions"], 2048)
        self.assertTrue(stream.closed)
        status = deepcopy(successor.STATUS)
        status["handle"] = reply["handle"]
        status["attempts"][0]["result"] = result
        status["attempts"][0]["attempt_id"] = result["attempt_id"]
        transport = legacy.Transport(legacy.Response(status, version="0.3"))
        with EzLLMRouterClient("http://synthetic.invalid", "token", transport=transport) as client:
            actual = client.get_status(
                {"submission_id": status["handle"]["submission_id"]}, contract_version="0.3"
            )
            self.assertEqual(len(actual["attempts"][0]["result"]["vectors"]), 25)

    def test_result_profile_is_checked_against_the_request_for_new_configurations(self):
        request, result = self.large_embedding()
        self.assertTrue(validation.result_valid(result, result["attempt_id"], request))
        for key, value in (
            ("profile_id", "profile.foreign"),
            ("model_ref", "model.foreign"),
            ("dimensions", 3),
        ):
            bad = {**result, key: value}
            self.assertFalse(validation.result_valid(bad, result["attempt_id"], request))
        rerank = deepcopy(successor.REQUEST)
        rerank["requested_configuration_ref"] = "cfg.newly.registered.rerank"
        rerank["input"]["ranking_profile_id"] = "rank.new"
        ranked = deepcopy(successor.COMPLETED["result"])
        ranked["ranking_profile_id"] = "rank.new"
        self.assertTrue(validation.result_valid(ranked, ranked["attempt_id"], rerank))
        self.assertFalse(
            validation.result_valid(
                {**ranked, "ranking_profile_id": "rank.foreign"}, ranked["attempt_id"], rerank
            )
        )
