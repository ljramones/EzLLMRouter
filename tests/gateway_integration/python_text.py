"""Installed Python client controls for the real gateway checkpoint."""
import json
import os
from pathlib import Path
import sys
import time

import httpx
from ezllmrouter_client import EzLLMRouterClient, EzLLMRouterError


BASE = json.loads(Path(__file__).with_name("request.json").read_text())


def count():
    with httpx.Client(trust_env=False) as client:
        return len(client.get(os.environ["EZLLMROUTER_RECEIVER_URL"] + "/observations").json()["arrivals"])


def receive(client, request):
    reply = client.submit(request, {"wait_ms": 3000})
    if reply["state"] == "delivered":
        return reply
    if reply["state"] != "pending":
        raise AssertionError("unexpected submission state")
    until = time.monotonic() + 5
    while time.monotonic() < until:
        status = client.getStatus({"submission_id": reply["handle"]["submission_id"]})
        if status["candidate_access"] == "present":
            return {"handle": reply["handle"], "candidate": status["candidate"]}
        time.sleep(.05)
    raise AssertionError("candidate unavailable")


def main():
    mode = sys.argv[1]
    with EzLLMRouterClient(os.environ["EZLLMROUTER_SERVICE_URL"], os.environ["EZLLMROUTER_DEV_TOKEN"]) as client:
        if mode == "cross_and_submit":
            first_id = sys.argv[2]
            before = count()
            first = client.getStatus({"submission_id": first_id})
            assert first["candidate_access"] == "present" and first["candidate"]["output_blocks"][0]["text"] == "Hello."
            assert count() == before
            request = json.loads(json.dumps(BASE))
            request["step_id"] = "step.dev04.python.text"
            reply = receive(client, request)
            status = client.getStatus({"submission_id": reply["handle"]["submission_id"]})
            assert reply["candidate"]["output_blocks"][0]["text"] == "Hello."
            assert status["attempts"][0]["usage"]["state"] == "available"
            assert status["attempts"][0]["usage"]["revision"]["attempt_id"] == reply["candidate"]["attempt_id"]
            assert count() == before + 1
            print(json.dumps({"actor": "installed-python", "cross_read": first_id,
                              "cross_candidate_id": first["candidate"]["candidate_id"],
                              "cross_attempt_id": first["candidate"]["attempt_id"],
                              "submission_id": reply["handle"]["submission_id"],
                              "attempt_id": reply["candidate"]["attempt_id"], "receiver_delta": 1,
                              "candidate_id": reply["candidate"]["candidate_id"],
                              "served_destination": reply["candidate"]["served_destination"],
                              "usage": status["attempts"][0]["usage"]}))
        elif mode == "guard_failure":
            before = count()
            request = json.loads(json.dumps(BASE))
            request["step_id"] = "step.dev04.guard.failure"
            try:
                client.submit(request, {"wait_ms": 3000})
            except EzLLMRouterError as exc:
                assert exc.code == "INTENT_PERSIST_FAILED" and exc.http_status == 503
                print(json.dumps({"actor": "installed-python", "negative": "guard_commit_failure",
                                  "error_code": exc.code, "receiver_delta": count() - before}))
            else:
                raise AssertionError("final guard commit failure was not observed")
            assert count() == before
        else:
            raise SystemExit("usage: python_text.py cross_and_submit SID | guard_failure")


if __name__ == "__main__":
    main()
