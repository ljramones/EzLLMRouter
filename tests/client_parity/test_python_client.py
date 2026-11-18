"""Contract-derived component cases; the installed consumer runs this unchanged."""
import copy
import json
from pathlib import Path
import unittest

import httpx

from duranki_client import DurankiClient, DurankiError

HERE = Path(__file__).resolve().parent
VECTOR_FILE = HERE / "vectors.json"
if not VECTOR_FILE.exists():
    VECTOR_FILE = HERE.parents[1] / "docs/contracts/wp-a-03-c01/DURANKI-WP-A-VECTORS-v0.3-CORRECTION-01.json"
EXAMPLES = json.loads(VECTOR_FILE.read_text())["examples"]


class Response:
    def __init__(self, value, status=200, version="0.2"):
        self.content = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        self.status_code = status
        self.headers = {"Duranki-Contract-Version": version}


class Transport:
    def __init__(self, response=None, callback=None, lost=False):
        self.response, self.callback, self.lost = response, callback, lost
        self.calls = []
        self.closed = False
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.callback:
            self.callback()
        if self.lost:
            raise OSError("synthetic lost reply")
        return self.response
    def close(self):
        self.closed = True


def selected():
    request = EXAMPLES["submit_text"]
    return {k: request[k] for k in ("task_id", "step_id", "step_revision", "execution_generation")}


def error(call, code):
    with unittest.TestCase().assertRaises(DurankiError) as caught:
        call()
    assert caught.exception.code == code, (caught.exception.code, code)
    return caught.exception


class ClientTests(unittest.TestCase):
    def client(self, response, *, status=200, callback=None, lost=False, version="0.2"):
        transport = Transport(Response(response, status, version), callback, lost)
        return DurankiClient("http://synthetic.invalid", "token.synthetic", transport=transport), transport

    def test_enabled_controls_and_wait_header(self):
        for name, action, status in [
            ("reply_delivered", lambda c: c.submit(EXAMPLES["submit_text"], {"wait_ms": 0}), 200),
            ("reply_pending", lambda c: c.submit(EXAMPLES["submit_text"], {}), 202),
            ("status_present", lambda c: c.getStatus({"submission_id": "submission.demo"}), 200),
            ("capabilities", lambda c: c.getCapabilities(), 200)]:
            with self.subTest(name=name):
                client, transport = self.client(EXAMPLES[name], status=status)
                with client:
                    result = action(client)
                self.assertEqual(result["contract_version"], "0.2")
                self.assertEqual(len(transport.calls), 1)
                self.assertTrue(transport.closed)
                method, _, kwargs = transport.calls[0]
                self.assertEqual(kwargs["headers"]["Duranki-Contract-Version"], "0.2")
                if method == "GET": self.assertNotIn("content", kwargs)
                elif name == "reply_delivered": self.assertEqual(kwargs["headers"]["Duranki-Wait-Ms"], "0")
                else: self.assertNotIn("Duranki-Wait-Ms", kwargs["headers"])
        client, transport = self.client(EXAMPLES["capabilities"])
        self.assertEqual(client.get_capabilities()["profile"], "initial_1a@1")
        client.close()

    def test_invalid_options_and_selectors_are_prefetch(self):
        client, transport = self.client(EXAMPLES["reply_delivered"])
        for options in ({"wait_ms": True}, {"wait_ms": 30001}, {"wait_ms": 1.5}, {"wait_ms": "0"}, {"extra": 1}):
            with self.subTest(options=options):
                self.assertEqual(error(lambda: client.submit(EXAMPLES["submit_text"], options), "SCHEMA_INVALID").http_status, None)
        for selector in ({"submission_id": ""}, {**selected(), "task_id": {}}, {"task_id": "task.demo"}):
            with self.subTest(selector=selector):
                error(lambda: client.getStatus(selector), "SCHEMA_INVALID")
        self.assertEqual(transport.calls, [])
        client.close()

    def test_malformed_handle_and_work_correspondence(self):
        for handle in ({}, {"submission_id": "submission.demo"},
                       {"submission_id": "submission.demo", "work_key": None}, "invalid"):
            for name, method in (("reply_delivered", "submit"), ("status_present", "status")):
                value = copy.deepcopy(EXAMPLES[name]); value["handle"] = handle
                client, transport = self.client(value)
                call = (lambda: client.submit(EXAMPLES["submit_text"])) if method == "submit" else \
                    (lambda: client.getStatus(selected()))
                caught = error(call, "INTERNAL_UNAVAILABLE")
                self.assertEqual(caught.selector, selected())
                self.assertEqual(len(transport.calls), 1)
                client.close()
        wrong = copy.deepcopy(EXAMPLES["reply_delivered"])
        wrong["handle"]["work_key"]["task_id"] = "task.other"
        client, _ = self.client(wrong)
        self.assertEqual(error(lambda: client.submit(EXAMPLES["submit_text"]), "INTERNAL_UNAVAILABLE").selector, selected())
        client.close()

    def test_selector_snapshot_both_forms(self):
        for kind in ("id", "work"):
            for original_reply in (True, False):
                with self.subTest(kind=kind, original_reply=original_reply):
                    selector = {"submission_id": "submission.demo"} if kind == "id" else selected()
                    expected = dict(selector)
                    value = copy.deepcopy(EXAMPLES["status_present"])
                    if not original_reply:
                        if kind == "id": value["handle"]["submission_id"] = "submission.other"
                        else: value["handle"]["work_key"]["task_id"] = "task.other"
                    def mutate():
                        if kind == "id": selector["submission_id"] = "submission.other"
                        else: selector["task_id"] = "task.other"
                    client, transport = self.client(value, callback=mutate)
                    if original_reply:
                        self.assertEqual(client.getStatus(selector)["handle"]["submission_id"], "submission.demo")
                    else:
                        self.assertEqual(error(lambda: client.getStatus(selector), "INTERNAL_UNAVAILABLE").selector, expected)
                    self.assertEqual(len(transport.calls), 1)
                    client.close()

    def test_transport_version_failure_and_accounting(self):
        client, transport = self.client(EXAMPLES["reply_delivered"], lost=True)
        caught = error(lambda: client.submit(EXAMPLES["submit_text"]), "TRANSPORT_OUTCOME_UNKNOWN")
        self.assertEqual((caught.retry_guidance, caught.selector, len(transport.calls)), ("query_first", selected(), 1))
        client.close()
        client, _ = self.client(EXAMPLES["reply_delivered"], version="9.9")
        self.assertEqual(error(lambda: client.submit(EXAMPLES["submit_text"]), "UNSUPPORTED_VERSION").selector, selected())
        client.close()
        client, transport = self.client(EXAMPLES["reply_delivered"])
        transport.response.content = b'{"contract_version":'
        caught = error(lambda: client.submit(EXAMPLES["submit_text"]), "TRANSPORT_OUTCOME_UNKNOWN")
        self.assertEqual((caught.retry_guidance, caught.selector, len(transport.calls)), ("query_first", selected(), 1))
        client.close()
        unknown = copy.deepcopy(EXAMPLES["reply_delivered"])
        revision = copy.deepcopy(EXAMPLES["usage_unknown_cost"])
        revision["attempt_id"] = unknown["candidate"]["attempt_id"]
        unknown["candidate"]["usage"] = {"state": "available", "revision": revision}
        client, _ = self.client(unknown)
        value = client.submit(EXAMPLES["submit_text"])
        self.assertEqual(value["candidate"]["usage"]["revision"]["cost"]["status"], "unknown")
        client.close()

    def test_deep_json_reply_keeps_typed_recovery_and_never_replays(self):
        requests = []
        deep = b"[" * 20000 + b"0" + b"]" * 20000
        def respond(request):
            requests.append(request)
            return httpx.Response(200, headers={"Duranki-Contract-Version": "0.2"}, content=deep)
        transport = httpx.Client(transport=httpx.MockTransport(respond), trust_env=False)
        client = DurankiClient("http://synthetic.invalid", "token.synthetic", transport=transport)
        original = selected()
        caught = error(lambda: client.submit(EXAMPLES["submit_text"]), "TRANSPORT_OUTCOME_UNKNOWN")
        self.assertEqual(caught.selector, original)
        self.assertEqual(caught.retry_guidance, "query_first")
        self.assertEqual(len(requests), 1)
        client.close()

    def test_nested_timestamp_and_usage_mismatch_are_typed(self):
        variants = []
        invalid_time = copy.deepcopy(EXAMPLES["reply_delivered"])
        invalid_time["candidate"]["observed_at"] = "2030-99-99T99:99:99Z"
        variants.append(invalid_time)
        wrong_usage = copy.deepcopy(EXAMPLES["reply_delivered"])
        revision = copy.deepcopy(EXAMPLES["usage_unknown_cost"])
        revision["attempt_id"] = "attempt.other"
        wrong_usage["candidate"]["usage"] = {"state": "available", "revision": revision}
        variants.append(wrong_usage)
        for value in variants:
            client, transport = self.client(value)
            caught = error(lambda: client.submit(EXAMPLES["submit_text"]), "INTERNAL_UNAVAILABLE")
            self.assertEqual(caught.selector, selected())
            self.assertEqual(len(transport.calls), 1)
            client.close()

    def test_status_404_is_not_nonexecution_proof(self):
        client, transport = self.client({"contract_version": "0.2", "error": EXAMPLES["error_forbidden"]["error"]}, status=404)
        caught = error(lambda: client.getStatus({"submission_id": "submission.demo"}), "NOT_FOUND_OR_FORBIDDEN")
        self.assertEqual(caught.http_status, 404)
        self.assertEqual(caught.selector, {"submission_id": "submission.demo"})
        self.assertIsNone(caught.handle)
        self.assertEqual(len(transport.calls), 1)
        client.close()

    def test_known_failure_is_distinct(self):
        for name, code, status in (("reply_failed_fdc", "FDC_REJECTED", 409),
                                   ("reply_failed_intent", "INTENT_PERSIST_FAILED", 503),
                                   ("reply_failed_remote", "REMOTE_EXECUTION_FAILED", 502)):
            with self.subTest(name=name):
                client, _ = self.client(EXAMPLES[name], status=status)
                caught = error(lambda: client.submit(EXAMPLES["submit_text"]), code)
                self.assertEqual(caught.http_status, status)
                self.assertEqual(caught.selector, selected())
                self.assertEqual(caught.attempt_id, EXAMPLES[name]["attempt_id"])
                self.assertEqual(caught.handle, EXAMPLES[name]["handle"])
                client.close()


if __name__ == "__main__":
    unittest.main()
