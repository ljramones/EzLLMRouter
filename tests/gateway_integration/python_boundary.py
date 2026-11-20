"""Installed Python client for controlled DEV-04 provider outcomes."""

from copy import deepcopy
import json
import os
from pathlib import Path
import sys

import httpx
from ezllmrouter_client import EzLLMRouterClient, EzLLMRouterError


BASE = json.loads(Path(__file__).with_name("request.json").read_text())
TEXT = {"422": "Simulate 422", "503": "Simulate 503", "close": "Simulate close"}


def arrivals():
    with httpx.Client(trust_env=False, timeout=2) as client:
        response = client.get(os.environ["EZLLMROUTER_RECEIVER_URL"] + "/observations")
        response.raise_for_status()
        return response.json()["arrivals"]


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "positive" and sys.argv[2].replace("_", "").isalnum():
        mode, label = "positive", sys.argv[2]
    elif len(sys.argv) == 2 and sys.argv[1] in TEXT:
        mode, label = sys.argv[1], sys.argv[1]
    else:
        raise SystemExit("usage: python_boundary.py 422|503|close|positive LABEL")
    request = deepcopy(BASE)
    request["step_id"] = "step.dev04.boundary." + label
    if os.environ["EZLLMROUTER_SERVICE_URL"].endswith(":8771"):
        request["generation_settings"]["total_timeout_ms"] = 30000
    if mode in TEXT:
        request["messages"][1]["blocks"][0]["text"] = TEXT[mode]
    before = arrivals()
    with EzLLMRouterClient(
        os.environ["EZLLMROUTER_SERVICE_URL"], os.environ["EZLLMROUTER_DEV_TOKEN"]
    ) as client:
        if mode == "positive":
            reply = client.submit(request, {"wait_ms": 3000})
            assert reply["state"] == "delivered"
            status = client.getStatus({"submission_id": reply["handle"]["submission_id"]})
            assert reply["candidate"]["output_blocks"][0]["text"] == "Hello."
            assert status["attempts"][0]["usage"]["state"] == "available"
            result = {
                "actor": "installed-python",
                "case": label,
                "state": "delivered",
                "submission_id": reply["handle"]["submission_id"],
                "attempt_id": reply["candidate"]["attempt_id"],
            }
        elif mode in ("422", "503"):
            try:
                client.submit(request, {"wait_ms": 3000})
            except EzLLMRouterError as error:
                assert (error.code, error.http_status) == ("REMOTE_EXECUTION_FAILED", 502)
                assert error.handle and error.attempt_id
                status = client.getStatus({"submission_id": error.handle["submission_id"]})
                assert status["submission_state"] == "failed_after_transmit"
                assert status["attempts"][0]["usage"]["state"] == "not_recorded"
                assert status["terminal_attempt_id"] == error.attempt_id
                result = {
                    "actor": "installed-python",
                    "case": mode,
                    "public_code": error.code,
                    "http_status": error.http_status,
                    "submission_id": error.handle["submission_id"],
                    "attempt_id": error.attempt_id,
                    "submission_state": status["submission_state"],
                    "usage_state": status["attempts"][0]["usage"]["state"],
                }
            else:
                raise AssertionError("controlled provider error accepted")
        else:
            reply = client.submit(request, {"wait_ms": 3000})
            assert reply["state"] == "pending"
            status = client.getStatus({"submission_id": reply["handle"]["submission_id"]})
            assert status["submission_state"] == "outcome_unknown"
            assert status["attempts"][0]["usage"]["state"] == "not_recorded"
            result = {
                "actor": "installed-python",
                "case": mode,
                "submission_id": reply["handle"]["submission_id"],
                "attempt_id": status["attempts"][0]["attempt_id"],
                "submission_state": status["submission_state"],
                "usage_state": status["attempts"][0]["usage"]["state"],
            }
    after = arrivals()
    assert len(after) == len(before) + 1
    assert after[-1]["sequence"] == len(after) and after[-1]["model"] == "model.demo"
    result["receiver_delta"] = 1
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
