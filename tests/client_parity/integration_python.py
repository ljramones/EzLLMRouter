"""Installed-package actor; standard import only, no source path injection."""

import copy
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

import httpx
from ezllmrouter_client import EzLLMRouterClient, EzLLMRouterError
import ezllmrouter_client

HERE = Path(__file__).resolve().parent
CORPUS = {x["id"]: x for x in json.loads((HERE / "scenarios.json").read_text())["cases"]}
BASE = json.loads((HERE / "request.json").read_text())
assert importlib.util.find_spec("ezllmrouter_server") is None
assert "site-packages" in str(Path(ezllmrouter_client.__file__).resolve())


def arrivals():
    with httpx.Client(trust_env=False, follow_redirects=False, timeout=5.0) as client:
        r = client.get(os.environ["EZLLMROUTER_RECEIVER_URL"] + "/observations")
        r.raise_for_status()
        return r.json()["arrivals"]


def wait_arrivals(expected):
    deadline = time.monotonic() + 3
    while True:
        observed = arrivals()
        if len(observed) >= expected:
            return observed
        if time.monotonic() >= deadline:
            raise AssertionError(f"receiver did not reach {expected} arrivals")
        time.sleep(0.025)


def no_send_drain(expected_count, duration=0.5):
    start = time.monotonic()
    deadline = start + duration
    while True:
        observed = arrivals()
        assert len(observed) == expected_count, "unexpected receiver send during negative drain"
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return observed, round((time.monotonic() - start) * 1000)
        time.sleep(min(0.025, remaining))


def case_request(item):
    value = copy.deepcopy(BASE)
    value["step_id"] = item["step_id"]
    value["execution_generation"] = item["execution_generation"]
    if "total_timeout_ms" in item:
        value["generation_settings"]["total_timeout_ms"] = item["total_timeout_ms"]
    return value


def reordered(value):
    if isinstance(value, dict):
        return {key: reordered(item) for key, item in reversed(list(value.items()))}
    if isinstance(value, list):
        return [reordered(item) for item in value]
    return value


def main():
    mode = sys.argv[1]
    with EzLLMRouterClient(
        os.environ["EZLLMROUTER_SERVICE_URL"], os.environ["EZLLMROUTER_DEV_TOKEN"]
    ) as client:
        if mode == "capabilities":
            result = client.getCapabilities()
            assert result["supported_features"] == ["text"]
            print(
                json.dumps(
                    {
                        "actor": "python",
                        "mode": mode,
                        "profile": result["profile"],
                        "module": str(Path(ezllmrouter_client.__file__).resolve()),
                        "version": importlib.metadata.version(
                            "cognitivedynamics-ezllmrouter-client"
                        ),
                    }
                )
            )
            return
        if mode in ("submit", "submit_reordered"):
            item = CORPUS[sys.argv[2]]
            before = arrivals()
            request = case_request(item)
            if mode == "submit_reordered":
                request = reordered(request)
            result = client.submit(request, {"wait_ms": item["wait_ms"]})
            assert result["state"] == item["expected_state"]
            if result["state"] == "delivered":
                assert result["candidate"]["output_blocks"][0]["text"] == item["expected_text"]
                assert result["candidate"]["usage"]["revision"]["cost"]["status"] == "unknown"
                if item.get("candidate_access_after"):
                    assert (
                        client.getStatus({"submission_id": result["handle"]["submission_id"]})[
                            "candidate_access"
                        ]
                        == item["candidate_access_after"]
                    )
            else:
                assert result["pending_result_policy"] == item["pending_result_policy"]
            after = wait_arrivals(len(before) + item["receiver_delta"])
            assert len(after) == len(before) + item["receiver_delta"]
            print(
                json.dumps(
                    {
                        "actor": "python",
                        "mode": mode,
                        "case": item["id"],
                        "state": result["state"],
                        "submission_id": result["handle"]["submission_id"],
                        "work_key": result["handle"]["work_key"],
                        "attempt_id": result.get("candidate", {}).get("attempt_id"),
                        "candidate_id": result.get("candidate", {}).get("candidate_id"),
                        "receiver_before": len(before),
                        "receiver_after": len(after),
                        "receiver_last": after[-1] if after else None,
                    }
                )
            )
            return
        if mode == "status_metadata":
            item = CORPUS[sys.argv[2]]
            sid = sys.argv[3]
            before = arrivals()
            deadline = time.monotonic() + 8
            while True:
                snapshot = client.getStatus({"submission_id": sid})
                if snapshot["submission_state"] == "completed":
                    break
                if time.monotonic() >= deadline:
                    raise AssertionError("metadata completion timeout")
                time.sleep(0.05)
            assert snapshot["candidate_access"] == item["candidate_access_after"]
            assert snapshot["result_unavailable_reason"] == item["result_unavailable_reason"]
            assert "candidate" not in snapshot
            assert len(arrivals()) == len(before)
            print(
                json.dumps(
                    {
                        "actor": "python",
                        "mode": mode,
                        "case": item["id"],
                        "submission_id": sid,
                        "candidate_access": snapshot["candidate_access"],
                        "reason": snapshot["result_unavailable_reason"],
                        "receiver_count": len(before),
                    }
                )
            )
            return
        if mode == "failure":
            item = CORPUS[sys.argv[2]]
            before = arrivals()
            try:
                client.submit(case_request(item), {"wait_ms": item["wait_ms"]})
            except EzLLMRouterError as exc:
                assert (
                    exc.code == item["expected_error"]
                    and exc.failure_stage == item["failure_stage"]
                )
                assert exc.handle and exc.attempt_id
                snapshot = client.getStatus({"submission_id": exc.handle["submission_id"]})
                assert snapshot["terminal_failure"]["code"] == exc.code
                assert snapshot["terminal_attempt_id"] == exc.attempt_id
                assert snapshot["candidate_access"] == "unavailable_due_failure"
                code, attempt_id = exc.code, exc.attempt_id
            else:
                raise AssertionError("expected stored failure")
            after = wait_arrivals(len(before) + item["receiver_delta"])
            drain_ms = None
            if item["receiver_delta"] == 0:
                after, drain_ms = no_send_drain(len(before))
            assert len(after) == len(before) + item["receiver_delta"]
            print(
                json.dumps(
                    {
                        "actor": "python",
                        "mode": mode,
                        "case": item["id"],
                        "code": code,
                        "attempt_id": attempt_id,
                        "receiver_before": len(before),
                        "receiver_after": len(after),
                        "negative_drain_ms": drain_ms,
                    }
                )
            )
            return
        if mode == "status":
            item = CORPUS[sys.argv[2]]
            sid = sys.argv[3]
            before = arrivals()
            deadline = time.monotonic() + 8
            while True:
                by_id = client.getStatus({"submission_id": sid})
                if by_id["submission_state"] == "completed":
                    break
                if time.monotonic() >= deadline:
                    raise AssertionError("retained completion timeout")
                time.sleep(0.05)
            selected = {k: BASE[k] for k in ("task_id", "step_revision")}
            selected.update(
                step_id=item["step_id"], execution_generation=item["execution_generation"]
            )
            by_work = client.getStatus(selected)
            assert by_id["handle"] == by_work["handle"]
            assert by_id["handle"]["submission_id"] == sid
            assert by_id["submission_state"] == "completed"
            assert by_id["candidate"]["candidate_id"] == by_work["candidate"]["candidate_id"]
            assert by_id["attempts"][0]["usage"]["revision"]["cost"]["status"] == "unknown"
            after = arrivals()
            assert len(after) == len(before)
            print(
                json.dumps(
                    {
                        "actor": "python",
                        "mode": mode,
                        "case": item["id"],
                        "submission_id": sid,
                        "candidate_id": by_id["candidate"]["candidate_id"],
                        "attempt_id": by_id["candidate"]["attempt_id"],
                        "receiver_count": len(after),
                    }
                )
            )
            return
        if mode == "forbidden_status":
            sid = sys.argv[2]
            before = arrivals()
            with EzLLMRouterClient(
                os.environ["EZLLMROUTER_SERVICE_URL"], os.environ["EZLLMROUTER_DEV_TOKEN_SECONDARY"]
            ) as other:
                try:
                    other.getStatus({"submission_id": sid})
                except EzLLMRouterError as exc:
                    assert exc.code == "NOT_FOUND_OR_FORBIDDEN" and exc.http_status == 404
                else:
                    raise AssertionError("second principal read first principal work")
            _after, drain_ms = no_send_drain(len(before))
            print(
                json.dumps(
                    {
                        "actor": "python",
                        "mode": mode,
                        "code": "NOT_FOUND_OR_FORBIDDEN",
                        "receiver_count": len(before),
                        "negative_drain_ms": drain_ms,
                    }
                )
            )
            return
        if mode == "auth":
            before = arrivals()
            with EzLLMRouterClient(
                os.environ["EZLLMROUTER_SERVICE_URL"], "invalid.synthetic.token"
            ) as invalid:
                try:
                    invalid.getCapabilities()
                except EzLLMRouterError as exc:
                    assert exc.code == "AUTHENTICATION_FAILED" and exc.http_status == 401
                else:
                    raise AssertionError("unauthorized client was accepted")
            after, drain_ms = no_send_drain(len(before))
            print(
                json.dumps(
                    {
                        "actor": "python",
                        "mode": mode,
                        "code": "AUTHENTICATION_FAILED",
                        "receiver_count": len(after),
                        "negative_drain_ms": drain_ms,
                    }
                )
            )
            return
    raise ValueError("unknown mode")


if __name__ == "__main__":
    main()
