"""Client boundary regressions shared by execution and external accounting."""

import unittest

import httpx

from ezllmrouter_client import (
    ClientError,
    EzLLMRouterClient,
    IntegrationClient,
    IntegrationInputError,
)
from ezllmrouter_client import _successor_validation as successor
from ezllmrouter_client.integration import _valid
from tests.unit import test_python_client_safety as safety


class ClientConsistencyTests(unittest.TestCase):
    def test_origins_and_credentials_are_validated_before_allocating_a_transport(self):
        for client_type in (EzLLMRouterClient, IntegrationClient):
            for origin in (
                "http://example.test/api",
                "http://example.test?",
                "http://example.test#",
                "http://user@example.test",
                "http://example.test:99999",
                "http://example.test:0",
                "\nhttp://example.test",
                "http://example.test\\path",
                "http://[broken",
                "http://example.test/\t",
            ):
                with self.subTest(client=client_type.__name__, origin=origin):
                    with self.assertRaises(TypeError):
                        client_type(origin, "test-token")
            for token in ("", "with space", "bad\r\nheader", "non-ascii-\u00e9"):
                with self.assertRaises(TypeError):
                    client_type("http://example.test", token)

    def test_diagnostics_redact_credentials_and_ipv6_origins_work(self):
        for client_type in (EzLLMRouterClient, IntegrationClient):
            with client_type("http://[::1]:8765/", "canary-secret") as client:
                self.assertEqual(client.base_url, "http://[::1]:8765")
                self.assertNotIn("canary-secret", repr(client))
                self.assertNotIn("canary-secret", repr(vars(client)))
                self.assertFalse(hasattr(client, "token"))

    def test_all_protocol_decode_errors_share_status_and_query_first_without_replay(self):
        for protocol in ("wire", "successor", "integration", "attribution"):
            with self.subTest(protocol=protocol):
                harness = safety.ClientTransportTests()
                stream = safety.RecordingStream([b'{"duplicate":1,"duplicate":2}'])
                try:
                    action, calls = harness.invoke(protocol, stream)
                    with self.assertRaises(ClientError) as caught:
                        action()
                    self.assertEqual(caught.exception.code, "TRANSPORT_OUTCOME_UNKNOWN")
                    self.assertEqual(caught.exception.http_status, 200)
                    self.assertEqual(caught.exception.retry_guidance, "query_first")
                    self.assertEqual(len(calls), 1)
                    self.assertTrue(stream.closed)
                finally:
                    harness.doCleanups()

    def test_invalid_accounting_input_has_a_common_root_and_preserves_type_error(self):
        def unexpected(_request):
            self.fail("invalid input must not reach transport")

        transport = httpx.Client(transport=httpx.MockTransport(unexpected))
        with IntegrationClient("http://example.test", "token", transport=transport) as client:
            for action in (
                lambda: client.submit_observation({}),
                lambda: client.submit_snapshot([]),
                lambda: client.create_dataset({}),
                lambda: client.recover_receipt("invalid/id", "event"),
            ):
                with self.assertRaises(IntegrationInputError) as caught:
                    action()
                self.assertIsInstance(caught.exception, TypeError)
                self.assertIsInstance(caught.exception, ClientError)
                self.assertEqual(caught.exception.code, "SCHEMA_INVALID")

    def test_schema_subset_agrees_on_constants_lengths_patterns_and_integer_bounds(self):
        cases = (
            (True, {"const": 1}, False),
            (True, {"enum": [1, 2]}, False),
            ("", {"type": "string", "minLength": 1}, False),
            ("long", {"type": "string", "maxLength": 3}, False),
            ("prefix-middle-suffix", {"type": "string", "pattern": "middle"}, True),
            (2**53, {"type": "integer"}, False),
            (True, {"type": "integer"}, False),
            (1, {"type": "boolean"}, False),
            ([1, 1], {"type": "array", "items": {"type": "integer"}, "uniqueItems": True}, False),
        )
        for value, shape, expected in cases:
            with self.subTest(value=value, shape=shape):
                self.assertEqual(_valid(value, shape), expected)
                self.assertEqual(successor.schema(value, shape), expected)

    def test_schema_text_policies_retain_protocol_differences(self):
        shape = {"type": "string"}
        self.assertTrue(_valid("line\nnext", shape))
        self.assertFalse(successor.schema("line\nnext", shape))
        for invalid in ("nul\0", "surrogate\ud800"):
            self.assertFalse(_valid(invalid, shape))
            self.assertFalse(successor.schema(invalid, shape))
        for validator in (_valid, successor.schema):
            with self.assertRaises(ValueError):
                validator("anything", {"type": "unsupported"})

    def test_accounting_utc_rejects_invalid_calendar_dates(self):
        schema = {"utc": {"type": "string"}}
        self.assertFalse(_valid("2026-02-30T00:00:00Z", {"$ref": "#/$defs/utc"}, schema))
        self.assertTrue(_valid("2026-02-28T00:00:00Z", {"$ref": "#/$defs/utc"}, schema))
