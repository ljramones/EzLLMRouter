"""Version-selected real HTTP ingress without a model executor."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import http.client
import json
from pathlib import Path
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
from duranki_server.core import Coordinator  # noqa: E402
from duranki_server.canonical import ContractError  # noqa: E402
from duranki_server.web import serve  # noqa: E402


class FakeSuccessor:
    calls = 0

    def submit(self, request, trusted, wait_ms, credential):
        self.calls += 1
        return 202, {"contract_version": "0.3", "state": "pending",
                     "handle": {"contract_version": "0.3", "submission_id": "submission.test",
                                "work_key": {"principal_id": trusted["principal_id"],
                                             **request["work_selector"]}},
                     "attempt_id": "attempt.test", "pending_result_policy": "pollable_public_synthetic"}

    def status(self, _sid, _trusted):
        return {"contract_version": "0.3", "read_only": True}


class WebBoundaryTests(unittest.TestCase):
    def test_selected_authentication_failure_is_strict_401(self):
        expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        trusted = {"principal_id": "user.demo", "task_id": "task.demo", "expires_at": expiry}
        coordinator = Coordinator(None, {"test.token": trusted}, {}, {}, {}, None, None, {}, {}, None)
        successor = FakeSuccessor()
        coordinator.successor = successor
        wire = serve("127.0.0.1", 0, coordinator)
        thread = threading.Thread(target=wire.serve_forever, daemon=True)
        thread.start()
        try:
            for method, path, authorization in (("POST", "/v1/submissions", None),
                                                ("GET", "/v1/submissions/submission.test", "Bearer wrong")):
                with self.subTest(method=method):
                    connection = http.client.HTTPConnection("127.0.0.1", wire.server_address[1], timeout=5)
                    headers = {"Duranki-Contract-Version": "0.3"}
                    if authorization is not None:
                        headers["Authorization"] = authorization
                    connection.request(method, path, b"{}" if method == "POST" else None, headers)
                    response = connection.getresponse()
                    value = json.loads(response.read())
                    self.assertEqual(response.status, 401)
                    self.assertEqual(response.getheader("Duranki-Contract-Version"), "0.3")
                    self.assertEqual(set(value), {"contract_version", "code", "correlation_id", "retry_guidance"})
                    self.assertEqual((value["contract_version"], value["code"], value["retry_guidance"]),
                                     ("0.3", "POLICY_DENIED", "never"))
                    self.assertTrue(value["correlation_id"].startswith("error."))
                    connection.close()
            connection = http.client.HTTPConnection("127.0.0.1", wire.server_address[1], timeout=5)
            connection.request("POST", "/v1/submissions", b"{malformed-json",
                               {"Duranki-Contract-Version": "0.3",
                                "Content-Type": "application/json"})
            denied = connection.getresponse()
            self.assertEqual((denied.status, denied.getheader("Connection")), (401, "close"))
            denied.read()
            connection.request("GET", "/v1/submissions/submission.test", headers={
                "Duranki-Contract-Version": "0.3", "Authorization": "Bearer test.token"})
            permitted = connection.getresponse()
            self.assertEqual(permitted.status, 200)
            permitted.read()
            connection.close()
            self.assertEqual(successor.calls, 0)
        finally:
            wire.shutdown()
            wire.server_close()
            thread.join(timeout=5)
            coordinator.pool.shutdown(wait=True)

    def test_cross_version_conflict_projects_each_strict_wire(self):
        expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        trusted = {"principal_id": "user.demo", "task_id": "task.demo", "expires_at": expiry}
        coordinator = Coordinator(None, {"test.token": trusted}, {}, {}, {}, None, None, {}, {}, None)
        successor = FakeSuccessor()
        coordinator.successor = successor
        def conflict(*_args, **_kwargs):
            raise ContractError("WORK_VERSION_CONFLICT", 409)
        coordinator.submit = conflict
        successor.submit = conflict
        wire = serve("127.0.0.1", 0, coordinator)
        threading.Thread(target=wire.serve_forever, daemon=True).start()
        try:
            for version, expected in (("0.2", "WORK_CONFLICT"),
                                      ("0.3", "WORK_VERSION_CONFLICT")):
                with self.subTest(version=version):
                    connection = http.client.HTTPConnection("127.0.0.1", wire.server_address[1], timeout=5)
                    body = json.dumps({"contract_version": version}).encode()
                    connection.request("POST", "/v1/submissions", body,
                                       {"Authorization": "Bearer test.token",
                                        "Duranki-Contract-Version": version,
                                        "Content-Type": "application/json"})
                    response = connection.getresponse()
                    value = json.loads(response.read())
                    connection.close()
                    error = value["error"] if version == "0.2" else value
                    self.assertEqual((response.status, error["code"], error["retry_guidance"]),
                                     (409, expected, "never"))
        finally:
            wire.shutdown()
            wire.server_close()
            coordinator.pool.shutdown(wait=True)

    def test_selected_ingress_rejects_before_service(self):
        expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        trusted = {"principal_id": "user.demo", "task_id": "task.demo", "expires_at": expiry}
        coordinator = Coordinator(None, {"test.token": trusted}, {}, {}, {}, None, None, {}, {}, None)
        successor = FakeSuccessor()
        coordinator.successor = successor
        wire = serve("127.0.0.1", 0, coordinator)
        threading.Thread(target=wire.serve_forever, daemon=True).start()
        port = wire.server_address[1]
        def post(body, headers=None, duplicates=()):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.putrequest("POST", "/v1/submissions")
            for key, value in (headers or {}).items():
                connection.putheader(key, value)
            for key, value in duplicates:
                connection.putheader(key, value)
            connection.putheader("Content-Length", str(len(body)))
            connection.endheaders(body)
            response = connection.getresponse()
            answer = response.status, json.loads(response.read())
            connection.close()
            return answer
        try:
            headers = {"Authorization": "Bearer test.token", "Duranki-Contract-Version": "0.3",
                       "Content-Type": "application/json"}
            request = {"contract_version": "0.3", "work_selector": {
                "task_id": "task.demo", "step_id": "step.demo", "step_revision": 1,
                "execution_generation": "gen.demo"}}
            raw = json.dumps(request).encode()
            status, _ = post(raw, {key: value for key, value in headers.items()
                                   if key != "Duranki-Contract-Version"})
            self.assertEqual(status, 426)
            status, answer = post(raw.replace(b'"0.3"', b'"0.2"'), headers)
            self.assertEqual((status, answer["code"]), (426, "UNSUPPORTED_VERSION"))
            status, answer = post(raw, headers, (("Duranki-Wait-Ms", "1"), ("Duranki-Wait-Ms", "2")))
            self.assertEqual((status, answer["code"]), (400, "SCHEMA_INVALID"))
            status, answer = post(b'{"contract_version":"0.3","contract_version":"0.3"}', headers)
            self.assertEqual((status, answer["code"]), (400, "MALFORMED_JSON"))
            self.assertEqual(successor.calls, 0)
            status, answer = post(raw, headers)
            self.assertEqual((status, answer["state"]), (202, "pending"))
            self.assertEqual(successor.calls, 1)
        finally:
            wire.shutdown()
            wire.server_close()
            coordinator.pool.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
