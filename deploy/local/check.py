"""Host-side authenticated profile check; prints metadata, never credentials."""
from __future__ import annotations

import http.client
import json
import secrets
import time


HOST = "127.0.0.1"
PORT = 8780
ORIGIN = "http://127.0.0.1:8780"


class OperatorClient:
    def __init__(self, password):
        self.password = password
        self.cookie = None
        self.csrf = None

    def call(self, method, path, body=None):
        connection = http.client.HTTPConnection(HOST, PORT, timeout=3)
        headers = {"Host": f"{HOST}:{PORT}", "Origin": ORIGIN}
        data = None
        if body is not None:
            data = json.dumps(body, separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"
        if self.cookie:
            headers["Cookie"] = self.cookie
        if method == "POST" and self.csrf:
            headers["X-EzLLMRouter-CSRF"] = self.csrf
        try:
            connection.request(method, path, body=data, headers=headers)
            response = connection.getresponse()
            raw = response.read()
            value = json.loads(raw)
            if path == "/operator/v1/login" and response.status == 200:
                self.cookie = response.getheader("Set-Cookie").split(";", 1)[0]
                self.csrf = value["csrf"]
            if response.status >= 400:
                raise RuntimeError(f"operator {response.status} {value.get('error')}")
            return value
        finally:
            connection.close()

    def login(self):
        self.call("POST", "/operator/v1/login", {"password": self.password})

    def health(self):
        overview = self.call("GET", "/operator/v1/overview")
        if overview["service"]["state"] != "live" or overview["worker"]["state"] != "live" or \
                overview["sender"]["state"] != "live":
            raise RuntimeError("one or more trusted boundaries unavailable")
        return overview

    def launch(self, kind):
        operation = "operation." + secrets.token_hex(16)
        try:
            self.call("POST", "/operator/v1/demos/" + kind, {"operation_id": operation})
        except (OSError, TimeoutError):
            # Query by the same operation ID; never retransmit the accepted POST.
            pass
        end = time.monotonic() + 30
        while time.monotonic() < end:
            value = self.call("GET", "/operator/v1/launch/" + operation)
            if value["state"] != "running":
                if value["state"] != "completed":
                    raise RuntimeError("demo " + kind + " ended " + value["state"])
                return value
            time.sleep(0.15)
        raise RuntimeError("demo status unresolved; do not retransmit " + operation)


def wait_health(password, seconds=60):
    end = time.monotonic() + seconds
    last = None
    while time.monotonic() < end:
        client = OperatorClient(password)
        try:
            client.login()
            return client, client.health()
        except (OSError, TimeoutError, RuntimeError, ValueError) as exc:
            last = type(exc).__name__
            time.sleep(0.25)
    raise RuntimeError("operator/worker readiness deadline: " + str(last))


def exercise(password):
    client, before = wait_health(password)
    initial = before["counts"]["submissions"]
    outcomes = [client.launch(kind) for kind in ("text", "tool", "no_store_text")]
    if [len(x["submission_ids"]) for x in outcomes] != [1, 2, 1] or \
            [x["caller_lookups"] for x in outcomes] != [0, 1, 0]:
        raise RuntimeError("unexpected demo inventory")
    ids = [sid for item in outcomes for sid in item["submission_ids"]]
    details = [client.call("GET", "/operator/v1/activity/" + sid) for sid in ids]
    if any(item["dispatch_receipt"]["present"] is not True for item in details):
        raise RuntimeError("missing final dispatch receipt")
    if details[-1]["candidate_access"] != "not_retained" or details[-1]["content_store_allowed"]:
        raise RuntimeError("no-store metadata mismatch")
    forbidden = ("candidate", "messages", "arguments", "prompt", "token", "secret")
    if any(key in item for item in details for key in forbidden):
        raise RuntimeError("operator detail contains forbidden content key")
    usage = client.call("GET", "/operator/v1/usage")
    after = client.health()
    if after["counts"]["submissions"] - initial != 4 or usage["attempts"] < 4:
        raise RuntimeError("operator submission accounting mismatch")
    return {"kind": "DEV-06 explicit synthetic operator exercise",
            "submission_ids": ids, "operation_ids": [x["operation_id"] for x in outcomes],
            "provider_requests_expected_delta": 4, "caller_lookups": 1,
            "no_store_submission_id": ids[-1], "before_submissions": initial,
            "after_submissions": after["counts"]["submissions"]}


def readback(password, receipt):
    client, overview = wait_health(password)
    for sid in receipt["submission_ids"]:
        detail = client.call("GET", "/operator/v1/activity/" + sid)
        if detail["submission_id"] != sid or detail["submission_state"] != "completed":
            raise RuntimeError("permitted metadata not retained on restart")
    no_store = client.call("GET", "/operator/v1/activity/" + receipt["no_store_submission_id"])
    if no_store["candidate_access"] != "not_retained":
        raise RuntimeError("no-store restart metadata mismatch")
    return {"service": overview["service"]["state"],
            "worker": overview["worker"]["state"],
            "retained_submission_ids": len(receipt["submission_ids"]),
            "no_store_candidate_access": no_store["candidate_access"]}
