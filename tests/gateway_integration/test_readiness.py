"""Exercise the exact boundary readiness probes against Duranki's HTTP handler."""
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import re
import shlex
import sys
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
from duranki_server.canonical import ContractError  # noqa: E402
from duranki_server.web import serve  # noqa: E402


TOKEN = "synthetic-readiness-token-0000000000000000"
REAL_URLOPEN = urllib.request.urlopen


def exact_probe(case):
    text = (ROOT / "tests/gateway_integration/boundary_steps.sh").read_text()
    pattern = (r"  logrun d04-" + str(case) +
               r"-readiness compose exec -T [A-Za-z_]+ python -c \\\n    '[\s\S]*?'\n")
    match = re.search(pattern, text)
    if match is None:
        raise AssertionError("readiness command missing")
    words = shlex.split(match.group(0))
    return words[words.index("-T") + 1], words[-1]


class CoordinatorDouble:
    def __init__(self):
        self.auth_calls = 0
        self.capability_calls = 0
        self.submissions = 0

    def authenticate(self, token):
        self.auth_calls += 1
        if token != TOKEN:
            raise ContractError("AUTHENTICATION_FAILED", 401)
        return {"principal_id": "synthetic.readiness"}

    def capabilities(self, trusted):
        self.capability_calls += 1
        assert trusted["principal_id"] == "synthetic.readiness"
        return {"contract_version": "0.2", "profile": "initial_1a@1", "features": ["text"]}

    def submit(self, *_args, **_kwargs):
        self.submissions += 1
        raise AssertionError("readiness must not submit work")


class ReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.coordinator = CoordinatorDouble()
        cls.server = serve("127.0.0.1", 0, cls.coordinator)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.probes = {case: exact_probe(case) for case in (5, 6)}

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        assert not cls.thread.is_alive()
        assert cls.coordinator.submissions == 0

    def setUp(self):
        self.requests = []

    def execute(self, code, *, token=TOKEN, strip_version=False, fail_first=0,
                always_unavailable=False):
        output = io.StringIO()

        def route(value, timeout=1):
            request = value if isinstance(value, urllib.request.Request) else urllib.request.Request(value)
            self.requests.append(request)
            if always_unavailable or len(self.requests) <= fail_first:
                raise urllib.error.URLError(ConnectionRefusedError("controlled not listening"))
            url = urlsplit(request.full_url)
            assert url.hostname == "127.0.0.1" and url.port in (8771, 8772)
            assert url.path == "/v1/capabilities"
            headers = dict(request.header_items())
            if strip_version:
                headers = {key: value for key, value in headers.items()
                           if key.lower() != "duranki-contract-version"}
            mapped = urllib.request.Request(
                f"http://127.0.0.1:{self.port}{url.path}", headers=headers,
                method=request.get_method())
            return REAL_URLOPEN(mapped, timeout=timeout)

        with (patch.dict(os.environ, {"DURANKI_DEV_TOKEN": token}),
              patch("urllib.request.urlopen", side_effect=route),
              patch("time.sleep"), redirect_stdout(output)):
            exec(compile(code, "<exact-boundary-readiness>", "exec"), {"__name__": "__main__"})
        self.assertNotIn(TOKEN, output.getvalue())
        return output.getvalue()

    def test_both_probes_require_authenticated_200(self):
        for case in (5, 6):
            with self.subTest(case=case):
                self.requests = []
                self.assertEqual(self.execute(self.probes[case][1]), "200\n")
                self.assertEqual(len(self.requests), 1)

    def test_bare_capabilities_request_is_426(self):
        code = 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8771/v1/capabilities",timeout=1)'
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.execute(code)
        self.assertEqual(error.exception.code, 426)

    def test_version_without_auth_is_401(self):
        code = ('import urllib.request; urllib.request.urlopen(urllib.request.Request('
                '"http://127.0.0.1:8771/v1/capabilities",'
                'headers={"Duranki-Contract-Version":"0.2"}),timeout=1)')
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.execute(code)
        self.assertEqual(error.exception.code, 401)

    def test_wrong_version_rejected_immediately(self):
        code = self.probes[5][1].replace('"Duranki-Contract-Version":"0.2"',
                                        '"Duranki-Contract-Version":"9.9"')
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.execute(code)
        self.assertEqual((error.exception.code, len(self.requests)), (426, 1))

    def test_bad_credential_rejected_immediately(self):
        for case in (5, 6):
            with self.subTest(case=case):
                self.requests = []
                with self.assertRaises(urllib.error.HTTPError) as error:
                    self.execute(self.probes[case][1], token="wrong-synthetic")
                self.assertEqual((error.exception.code, len(self.requests)), (401, 1))

    def test_missing_version_rejected_immediately(self):
        for case in (5, 6):
            with self.subTest(case=case):
                self.requests = []
                with self.assertRaises(urllib.error.HTTPError) as error:
                    self.execute(self.probes[case][1], strip_version=True)
                self.assertEqual((error.exception.code, len(self.requests)), (426, 1))

    def test_transient_connection_failure_then_success(self):
        for case in (5, 6):
            with self.subTest(case=case):
                self.requests = []
                self.assertEqual(self.execute(self.probes[case][1], fail_first=1), "200\n")
                self.assertEqual(len(self.requests), 2)

    def test_connection_retry_is_bounded(self):
        with self.assertRaises(urllib.error.URLError):
            self.execute(self.probes[5][1], always_unavailable=True)
        self.assertEqual(len(self.requests), 60)

    def test_existing_consumer_environment_supplies_token(self):
        for case in (5, 6):
            role, code = self.probes[case]
            self.assertEqual(role, "python_consumer")
            self.assertIn('os.environ["DURANKI_DEV_TOKEN"]', code)
            self.assertNotIn(TOKEN, code)
        compose = (ROOT / "tests/gateway_integration/compose.yaml").read_text()
        netns = compose.split("  netns:", 1)[1].split("  receiver:", 1)[0]
        consumer = compose.split("  python_consumer:", 1)[1].split("  js_consumer:", 1)[0]
        self.assertNotIn("DURANKI_DEV_TOKEN", netns)
        self.assertIn("DURANKI_DEV_TOKEN: ${DURANKI_DEV_TOKEN:?}", consumer)

    def test_probe_only_reads_capabilities(self):
        self.execute(self.probes[5][1])
        self.assertTrue(all(request.get_method() == "GET" for request in self.requests))
        self.assertEqual(self.coordinator.submissions, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
