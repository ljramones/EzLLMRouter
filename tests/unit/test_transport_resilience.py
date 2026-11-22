"""The Python owned transport runs the same real HTTP/TLS cases as native SDKs."""

from collections import Counter
import unittest

from ezllmrouter_client import EzLLMRouterClient, EzLLMRouterError
from tests.client_languages import http_fixture as fixture


class OwnedHTTPResilienceTests(unittest.TestCase):
    def test_shared_matrix_bounds_replies_and_never_redirects_or_replays(self):
        fixture.COUNTS.clear()
        with fixture.fixture() as env:
            for row in fixture.POLICY["cases"]:
                with self.subTest(case=row["id"]):
                    origin = env[
                        "EZLLMROUTER_TEST_TLS_ORIGIN"
                        if row["id"] == "untrusted_tls"
                        else "EZLLMROUTER_TEST_ORIGIN"
                    ]
                    with EzLLMRouterClient(
                        origin,
                        "synthetic-native-" + row["id"],
                        total_timeout=row["timeout_ms"] / 1000,
                    ) as client:
                        if row["code"] is None:
                            self.assertEqual(client.get_capabilities()["profile"], "initial_1a@1")
                        else:
                            with self.assertRaises(EzLLMRouterError) as error:
                                client.get_capabilities()
                            self.assertEqual(error.exception.code, row["code"])
                            self.assertEqual(error.exception.retry_guidance, row["retry_guidance"])
                            self.assertIn(error.exception.http_status or 0, row["http_status"])
        expected = Counter(
            {row["id"]: row["requests"] for row in fixture.POLICY["cases"] if row["requests"]}
        )
        self.assertEqual(fixture.COUNTS, expected)
