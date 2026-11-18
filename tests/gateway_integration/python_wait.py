"""Installed-client actors for the selected lower-pool and context experiment."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import threading
import time

import httpx
from duranki_client import DurankiClient, DurankiError


BASE = json.loads(Path(__file__).with_name("request.json").read_text())


def receiver_count():
    with httpx.Client(trust_env=False, timeout=2) as client:
        return len(client.get(os.environ["DURANKI_RECEIVER_URL"] + "/observations").json()["arrivals"])


def request(label, text):
    value = deepcopy(BASE)
    value["step_id"] = "step.dev04.wait." + label
    value["messages"][1]["blocks"][0]["text"] = text
    value["generation_settings"]["total_timeout_ms"] = 30000
    return value


def client(token=None):
    return DurankiClient(os.environ["DURANKI_SERVICE_URL"], token or os.environ["DURANKI_DEV_TOKEN"])


def submit_pending(label, text):
    with client() as installed:
        reply = installed.submit(request(label, text), {"wait_ms": 0})
    assert reply["state"] == "pending"
    print(json.dumps({"actor": "installed-python", "case": label,
                      "submission_id": reply["handle"]["submission_id"], "state": "pending"}))


def status(sid):
    with client() as installed:
        latest = None
        until = time.monotonic() + 5
        while time.monotonic() < until:
            latest = installed.getStatus({"submission_id": sid})
            if latest["submission_state"] not in ("admitted", "running"):
                break
            time.sleep(0.05)
    assert latest is not None
    print(json.dumps({"actor": "installed-python", "case": "status", "submission_id": sid,
                      "submission_state": latest["submission_state"],
                      "candidate_access": latest["candidate_access"],
                      "attempt_id": latest["attempts"][0]["attempt_id"],
                      "dispatch_state": latest["attempts"][0]["dispatch_state"],
                      "terminal_error_code": (latest.get("terminal_failure") or {}).get("code"),
                      "terminal_attempt_id": latest.get("terminal_attempt_id")}))


def swapped():
    before = receiver_count()
    with client(os.environ["DURANKI_DEV_TOKEN"] + ".alternate") as installed:
        try:
            installed.submit(request("swapped", "Simulate swapped context"), {"wait_ms": 3000})
        except DurankiError as error:
            assert (error.code, error.http_status) == ("FDC_REJECTED", 409)
            result = {"actor": "installed-python", "case": "swapped", "code": error.code}
        else:
            raise AssertionError("swapped context accepted")
    assert receiver_count() == before
    result["receiver_delta"] = 0
    print(json.dumps(result))


def overlap():
    before = receiver_count()
    barrier = threading.Barrier(2)

    def one(label, token):
        with client(token) as installed:
            barrier.wait(timeout=5)
            reply = installed.submit(request(label, "Hi"), {"wait_ms": 3000})
            assert reply["state"] == "delivered"
            latest = installed.getStatus({"submission_id": reply["handle"]["submission_id"]})
            assert latest["candidate_access"] == "present"
            return {"label": label, "submission_id": reply["handle"]["submission_id"],
                    "attempt_id": reply["candidate"]["attempt_id"]}

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(one, "overlap_primary", os.environ["DURANKI_DEV_TOKEN"])
        second = pool.submit(one, "overlap_alternate", os.environ["DURANKI_DEV_TOKEN"] + ".alternate")
        rows = [first.result(timeout=10), second.result(timeout=10)]
    assert len({row["attempt_id"] for row in rows}) == 2
    assert receiver_count() == before + 2
    print(json.dumps({"actor": "installed-python", "case": "overlap",
                      "receiver_delta": 2, "contexts": rows}))


def main():
    mode = sys.argv[1]
    if mode == "hold":
        submit_pending(sys.argv[2], "Simulate hold")
    elif mode == "queued":
        submit_pending(sys.argv[2], "Hi")
    elif mode == "status":
        status(sys.argv[2])
    elif mode == "swapped":
        swapped()
    elif mode == "overlap":
        overlap()
    else:
        raise SystemExit("usage: python_wait.py hold LABEL|queued LABEL|status SID|swapped|overlap")


if __name__ == "__main__":
    main()
