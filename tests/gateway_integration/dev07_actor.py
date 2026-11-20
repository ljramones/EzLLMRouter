"""Installed Python client in a disposable DEV-07 actor container.

The trusted driver sends the private token on stdin. Stdout contains one safe
JSON result; no prompt, credential or raw HTTP response is exported.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
import sys
import time

from ezllmrouter_client import EzLLMRouterClient, EzLLMRouterError


BASE = json.loads(Path(__file__).with_name("request.json").read_text())
SCENARIOS = json.loads(Path(__file__).with_name("scenarios.json").read_text())
IDENT = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")


def candidate(client, request, wait_ms, no_store=False):
    reply = client.submit(request, {"wait_ms": wait_ms})
    sid = reply["handle"]["submission_id"]
    if reply["state"] == "delivered":
        return reply["candidate"], sid
    if reply["state"] != "pending" or no_store:
        raise RuntimeError("candidate unavailable after bounded wait")
    end = time.monotonic() + 8
    while time.monotonic() < end:
        status = client.getStatus({"submission_id": sid})
        if status["candidate_access"] == "present":
            return status["candidate"], sid
        if status["submission_state"] != "admitted":
            raise RuntimeError("candidate not delivered")
        time.sleep(0.1)
    raise RuntimeError("candidate unresolved")


def main():
    value = json.loads(sys.stdin.read(4096))
    if type(value) is not dict or "mode" not in value or "token" not in value:
        raise ValueError("actor input shape")
    token = value["token"]
    if type(token) is not str or len(token) < 32:
        raise ValueError("missing private actor credential")
    if value["mode"] == "status":
        if (
            set(value) != {"token", "mode", "submission_id"}
            or type(value["submission_id"]) is not str
            or not IDENT.fullmatch(value["submission_id"])
        ):
            raise ValueError("status input shape")
        with EzLLMRouterClient("http://127.0.0.1:8773", token) as client:
            status = client.getStatus({"submission_id": value["submission_id"]})
        attempts = status.get("attempts") or []
        print(
            json.dumps(
                {
                    "kind": "status",
                    "submission_id": value["submission_id"],
                    "submission_state": status["submission_state"],
                    "candidate_access": status["candidate_access"],
                    "attempt_id": attempts[0]["attempt_id"] if attempts else None,
                    "dispatch_state": attempts[0]["dispatch_state"] if attempts else None,
                    "terminal_error_code": (status.get("terminal_failure") or {}).get("code"),
                }
            )
        )
        return
    if set(value) != {"token", "configuration_ref", "step_id", "generation", "mode"}:
        raise ValueError("actor input shape")
    for key in ("configuration_ref", "step_id", "generation"):
        if type(value[key]) is not str or not IDENT.fullmatch(value[key]):
            raise ValueError("invalid actor work identity")
    mode = value["mode"]
    if mode not in ("text", "hold", "pending_hold", "pending_text", "no_store", "tool", "deny"):
        raise ValueError("invalid actor mode")
    req = deepcopy(BASE)
    req["requested_configuration_ref"] = value["configuration_ref"]
    req["step_id"] = value["step_id"]
    req["execution_generation"] = value["generation"]
    if mode in ("hold", "pending_hold", "pending_text"):
        req["generation_settings"]["total_timeout_ms"] = 30000
    if mode in ("hold", "pending_hold"):
        req["messages"][1]["blocks"][0]["text"] = "Simulate hold"
    if mode == "no_store":
        req["messages"][1]["blocks"][0]["source_labels"] = {
            "lineage_ids": ["src.user.no_store"],
            "sensitivity": "confidential",
            "restrictions": ["no.content.store"],
        }
    if mode == "tool":
        req["messages"][1]["blocks"][0]["text"] = "Use lookup for synthetic."
        req["requested_features"] = ["text", "tools"]
        req["tool_definitions"] = [deepcopy(SCENARIOS["tool_definition"])]
        req["tool_choice"] = "auto"
    with EzLLMRouterClient("http://127.0.0.1:8773", token) as client:
        if mode in ("pending_hold", "pending_text"):
            reply = client.submit(req, {"wait_ms": 0})
            if reply["state"] != "pending":
                raise AssertionError("pending actor did not return a handle")
            print(
                json.dumps(
                    {
                        "kind": mode,
                        "submission_id": reply["handle"]["submission_id"],
                        "state": "pending",
                    }
                )
            )
            return
        if mode == "deny":
            try:
                client.submit(req, {"wait_ms": 3000})
            except EzLLMRouterError as exc:
                print(
                    json.dumps(
                        {
                            "kind": "denied",
                            "code": exc.code,
                            "http_status": exc.http_status,
                            "failure_stage": exc.failure_stage,
                            "attempt_id": exc.attempt_id,
                            "submission_id": (exc.handle or {}).get("submission_id"),
                        }
                    )
                )
                return
            raise AssertionError("denied actor was accepted")
        first, sid = candidate(
            client, req, 30000 if mode == "hold" else 3000, no_store=mode == "no_store"
        )
        ids = [sid]
        lookups = 0
        if mode == "tool":
            calls = [block for block in first["output_blocks"] if block["kind"] == "tool_call"]
            if len(calls) != 1 or calls[0]["arguments"] != {"key": "synthetic"}:
                raise AssertionError("unexpected caller-owned lookup")
            second = deepcopy(req)
            second["execution_generation"] = value["generation"] + ".followup"
            second["messages"].append({"role": "assistant", "blocks": [calls[0]]})
            second["messages"].append(
                {
                    "role": "tool",
                    "blocks": [
                        {
                            "block_id": "block.result.1",
                            "kind": "tool_result",
                            "call_id": calls[0]["call_id"],
                            "result_value": {"value": "synthetic"},
                            "source_labels": deepcopy(SCENARIOS["result_source_labels"]),
                        }
                    ],
                }
            )
            final, next_sid = candidate(client, second, 3000)
            if final["finish_reason"] != "stop":
                raise AssertionError("tool followup incomplete")
            ids.append(next_sid)
            lookups = 1
        status = client.getStatus({"submission_id": sid})
        if mode == "no_store" and status["candidate_access"] != "not_retained":
            raise AssertionError("no-store status retained candidate")
        print(
            json.dumps(
                {
                    "kind": mode,
                    "submission_ids": ids,
                    "attempt_id": first["attempt_id"],
                    "selected_model": first["served_destination"]["model"],
                    "candidate_access": status["candidate_access"],
                    "caller_lookups": lookups,
                    "price_version": status["attempts"][0]["usage"]
                    .get("revision", {})
                    .get("price_version"),
                    "cost": status["attempts"][0]["usage"].get("revision", {}).get("cost"),
                }
            )
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("DEV-07 actor failed: " + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
