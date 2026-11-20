"""Installed Python client caller: the only Python code that executes lookup."""

import json
import os
from pathlib import Path
import sys
import time

import httpx
from ezllmrouter_client import EzLLMRouterClient, EzLLMRouterError


BASE = json.loads(Path(__file__).with_name("request.json").read_text())
CORPUS = json.loads(Path(__file__).with_name("scenarios.json").read_text())
CASE = next(x for x in CORPUS["cases"] if x["actor"] == "python")
TOOL = CORPUS["tool_definition"]
RESULT_LABEL = CORPUS["result_source_labels"]
executions = []


def lookup(arguments):
    if arguments != CASE["arguments"]:
        raise AssertionError("caller allowlist rejected arguments")
    executions.append({"tool": "lookup", "arguments": arguments})
    return CASE["result"]


def receive(client, request):
    reply = client.submit(request, {"wait_ms": 3000})
    if reply["state"] == "delivered":
        return reply
    if reply["state"] != "pending":
        raise AssertionError("no usable candidate")
    until = time.monotonic() + 5
    while time.monotonic() < until:
        status = client.getStatus({"submission_id": reply["handle"]["submission_id"]})
        if status["candidate_access"] == "present":
            return {
                "state": "delivered",
                "handle": reply["handle"],
                "candidate": status["candidate"],
            }
        if status["submission_state"] != "admitted":
            raise AssertionError("terminal without usable candidate")
        time.sleep(0.05)
    raise AssertionError("candidate did not become available")


def observed_count():
    with httpx.Client(trust_env=False, follow_redirects=False) as client:
        response = client.get(os.environ["EZLLMROUTER_RECEIVER_URL"] + "/observations")
        response.raise_for_status()
        return len(response.json()["arrivals"])


def cycle(alternative=False):
    with EzLLMRouterClient(
        os.environ["EZLLMROUTER_SERVICE_URL"], os.environ["EZLLMROUTER_DEV_TOKEN"]
    ) as client:
        before = observed_count()
        first = json.loads(json.dumps(BASE))
        first.update(
            step_id=CASE["step_id"],
            execution_generation="gen.3" if alternative else "gen.1",
            requested_features=["text", "tools"],
            tool_definitions=[TOOL],
            tool_choice="auto",
        )
        first["messages"][1]["blocks"][0]["text"] = "Use lookup for synthetic."
        first_reply = receive(client, first)
        first_candidate = first_reply["candidate"]
        assert len(executions) == 0 and first_candidate["finish_reason"] == "tool_calls"
        assert len(first_candidate["output_blocks"]) == 1
        call = first_candidate["output_blocks"][0]
        assert call["kind"] == "tool_call" and call["tool_name"] == "lookup"
        first_status = client.getStatus({"submission_id": first_reply["handle"]["submission_id"]})
        assert first_status["candidate_access"] == "present"
        result = lookup(call["arguments"])
        second = json.loads(json.dumps(first))
        second["execution_generation"] = "gen.4" if alternative else "gen.2"
        result_kind = "result_text" if alternative else CASE["result_kind"]
        submitted_result = "value.synthetic" if alternative else result
        second["messages"].append({"role": "assistant", "blocks": [call]})
        second["messages"].append(
            {
                "role": "tool",
                "blocks": [
                    {
                        "block_id": "block.result.1",
                        "kind": "tool_result",
                        "call_id": call["call_id"],
                        result_kind: submitted_result,
                        "source_labels": RESULT_LABEL,
                    }
                ],
            }
        )
        second_reply = receive(client, second)
        second_candidate = second_reply["candidate"]
        assert second_candidate["output_blocks"][0]["text"] == CASE["final_text"]
        second_status = client.getStatus({"submission_id": second_reply["handle"]["submission_id"]})
        after = observed_count()
        assert (
            after - before == CASE["model_posts"]
            and len(executions) == CASE["caller_tool_executions"]
        )
        assert first_candidate["attempt_id"] != second_candidate["attempt_id"]
        assert first_candidate["candidate_id"] != second_candidate["candidate_id"]
        assert first_status["attempts"][0]["usage"]["state"] == "available"
        assert second_status["attempts"][0]["usage"]["state"] == "available"
        assert (
            first_status["attempts"][0]["usage"]["revision"]["attempt_id"]
            == first_candidate["attempt_id"]
        )
        assert (
            second_status["attempts"][0]["usage"]["revision"]["attempt_id"]
            == second_candidate["attempt_id"]
        )
        print(
            json.dumps(
                {
                    "actor": "python",
                    "variant": "alternate" if alternative else "baseline",
                    "result_kind": result_kind,
                    "first_submission_id": first_reply["handle"]["submission_id"],
                    "second_submission_id": second_reply["handle"]["submission_id"],
                    "first_candidate_id": first_candidate["candidate_id"],
                    "second_candidate_id": second_candidate["candidate_id"],
                    "first_attempt_id": first_candidate["attempt_id"],
                    "second_attempt_id": second_candidate["attempt_id"],
                    "call_id": call["call_id"],
                    "provider_sends_delta": after - before,
                    "caller_tool_executions": len(executions),
                    "result": submitted_result,
                    "destinations": [
                        first_candidate["served_destination"],
                        second_candidate["served_destination"],
                    ],
                    "usage": [
                        first_status["attempts"][0]["usage"],
                        second_status["attempts"][0]["usage"],
                    ],
                }
            )
        )


def status(submission_id, expected_kind="tool_call"):
    with EzLLMRouterClient(
        os.environ["EZLLMROUTER_SERVICE_URL"], os.environ["EZLLMROUTER_DEV_TOKEN"]
    ) as client:
        before = observed_count()
        value = client.getStatus({"submission_id": submission_id})
        after = observed_count()
        assert value["candidate_access"] == "present" and after == before and not executions
        assert value["candidate"]["output_blocks"][0]["kind"] == expected_kind
        print(
            json.dumps(
                {
                    "actor": "python",
                    "cross_read": submission_id,
                    "candidate_id": value["candidate"]["candidate_id"],
                    "attempt_id": value["candidate"]["attempt_id"],
                    "usage_state": value["attempts"][0]["usage"]["state"],
                    "provider_sends_delta": 0,
                    "caller_tool_executions": 0,
                }
            )
        )


def status_by_work(step_id, generation, expected_kind):
    with EzLLMRouterClient(
        os.environ["EZLLMROUTER_SERVICE_URL"], os.environ["EZLLMROUTER_DEV_TOKEN"]
    ) as client:
        before = observed_count()
        selector = {
            "task_id": BASE["task_id"],
            "step_id": step_id,
            "step_revision": BASE["step_revision"],
            "execution_generation": generation,
        }
        value = client.getStatus(selector)
        after = observed_count()
        assert value["candidate_access"] == "present" and after == before and not executions
        assert value["candidate"]["output_blocks"][0]["kind"] == expected_kind
        assert value["attempts"][0]["usage"]["state"] == "available"
        print(
            json.dumps(
                {
                    "actor": "python",
                    "by_work": selector,
                    "submission_id": value["handle"]["submission_id"],
                    "candidate_id": value["candidate"]["candidate_id"],
                    "attempt_id": value["candidate"]["attempt_id"],
                    "provider_sends_delta": 0,
                    "caller_tool_executions": 0,
                }
            )
        )


def text_regression():
    with EzLLMRouterClient(
        os.environ["EZLLMROUTER_SERVICE_URL"], os.environ["EZLLMROUTER_DEV_TOKEN"]
    ) as client:
        before = observed_count()
        request = json.loads(json.dumps(BASE))
        request["step_id"] = "step.dev03.text"
        reply = receive(client, request)
        candidate = reply["candidate"]
        status = client.getStatus({"submission_id": reply["handle"]["submission_id"]})
        after = observed_count()
        assert candidate["output_blocks"][0]["text"] == "Hello."
        assert status["candidate"]["candidate_id"] == candidate["candidate_id"]
        assert after - before == 1 and not executions
        print(
            json.dumps(
                {
                    "actor": "python",
                    "text_regression": "PASS",
                    "submission_id": reply["handle"]["submission_id"],
                    "provider_sends_delta": 1,
                    "caller_tool_executions": 0,
                }
            )
        )


def no_store_cycle():
    with EzLLMRouterClient(
        os.environ["EZLLMROUTER_SERVICE_URL"], os.environ["EZLLMROUTER_DEV_TOKEN"]
    ) as client:
        before = observed_count()
        first = json.loads(json.dumps(BASE))
        first.update(
            step_id="step.dev03.no_store",
            execution_generation="gen.1",
            requested_features=["text", "tools"],
            tool_definitions=[TOOL],
            tool_choice="auto",
        )
        first["messages"][1]["blocks"][0].update(
            text="Use lookup for synthetic.",
            source_labels={
                "lineage_ids": ["src.user.no_store"],
                "sensitivity": "confidential",
                "restrictions": ["no.content.store"],
            },
        )
        first_reply = receive(client, first)
        call = first_reply["candidate"]["output_blocks"][0]
        assert call["kind"] == "tool_call" and call["source_labels"]["restrictions"] == [
            "no.content.store"
        ]
        first_status = client.getStatus({"submission_id": first_reply["handle"]["submission_id"]})
        assert (
            first_status["candidate_access"] == "not_retained" and "candidate" not in first_status
        )
        result = lookup(call["arguments"])
        second = json.loads(json.dumps(first))
        second["execution_generation"] = "gen.2"
        second["messages"].extend(
            [
                {"role": "assistant", "blocks": [call]},
                {
                    "role": "tool",
                    "blocks": [
                        {
                            "block_id": "block.result.1",
                            "kind": "tool_result",
                            "call_id": call["call_id"],
                            "result_value": result,
                            "source_labels": RESULT_LABEL,
                        }
                    ],
                },
            ]
        )
        forged = json.loads(json.dumps(second))
        forged["execution_generation"] = "gen.3"
        forged["messages"][2]["blocks"][0]["arguments"]["key"] = "forged"
        try:
            client.submit(forged, {"wait_ms": 3000})
        except EzLLMRouterError as exc:
            assert exc.code == "SOURCE_INVALID" and exc.http_status == 422
        else:
            raise AssertionError("forged live source accepted")
        negative_before = observed_count()
        stable_start = time.monotonic()
        time.sleep(5.2)
        client.getCapabilities()
        negative_after = observed_count()
        stable_ms = int((time.monotonic() - stable_start) * 1000)
        assert stable_ms >= 5000 and negative_before == negative_after == before + 1
        final_reply = receive(client, second)
        final = final_reply["candidate"]
        assert final["output_blocks"][0]["text"] == "Lookup: synthetic"
        assert final["output_blocks"][0]["source_labels"]["restrictions"] == ["no.content.store"]
        final_status = client.getStatus({"submission_id": final_reply["handle"]["submission_id"]})
        assert (
            final_status["candidate_access"] == "not_retained" and "candidate" not in final_status
        )
        after = observed_count()
        assert after - before == 2 and len(executions) == 1
        print(
            json.dumps(
                {
                    "actor": "python",
                    "variant": "live_no_store",
                    "first_submission_id": first_reply["handle"]["submission_id"],
                    "second_submission_id": final_reply["handle"]["submission_id"],
                    "provider_sends_delta": after - before,
                    "caller_tool_executions": len(executions),
                    "forged_source_rejected": True,
                    "negative_stable_ms": stable_ms,
                    "destinations": [
                        first_reply["candidate"]["served_destination"],
                        final["served_destination"],
                    ],
                    "candidate_access": [
                        first_status["candidate_access"],
                        final_status["candidate_access"],
                    ],
                }
            )
        )


def tool_request(step_id, prompt, no_store=False):
    request = json.loads(json.dumps(BASE))
    request.update(
        step_id=step_id,
        execution_generation="gen.1",
        requested_features=["text", "tools"],
        tool_definitions=[TOOL],
        tool_choice="auto",
    )
    request["messages"][1]["blocks"][0]["text"] = prompt
    if no_store:
        request["messages"][1]["blocks"][0]["source_labels"] = {
            "lineage_ids": ["src.user.no_store"],
            "sensitivity": "confidential",
            "restrictions": ["no.content.store"],
        }
    return request


def stable_receiver_count(client, expected, duration=0.6):
    until = time.monotonic() + 3
    while time.monotonic() < until and observed_count() < expected:
        time.sleep(0.02)
    assert observed_count() == expected
    start = time.monotonic()
    time.sleep(duration)
    client.getCapabilities()  # Service remains responsive throughout the negative horizon.
    after = observed_count()  # Receiver remains responsive and count stays stable.
    elapsed = int((time.monotonic() - start) * 1000)
    assert elapsed >= 500 and after == expected
    return elapsed


def wait_expiry_no_store():
    with EzLLMRouterClient(
        os.environ["EZLLMROUTER_SERVICE_URL"], os.environ["EZLLMROUTER_DEV_TOKEN"]
    ) as client:
        before = observed_count()
        request = tool_request("step.dev03.wait.no_store", "Use lookup for synthetic wait.", True)
        reply = client.submit(request, {"wait_ms": 0})
        assert (
            reply["state"] == "pending"
            and reply["pending_result_policy"] == "metadata_only_no_store"
        )
        stable_ms = stable_receiver_count(client, before + 1)
        status = client.getStatus({"submission_id": reply["handle"]["submission_id"]})
        assert (
            status["submission_state"] == "completed"
            and status["candidate_access"] == "not_retained"
        )
        assert (
            status["result_unavailable_reason"] == "wait_expired_no_store"
            and "candidate" not in status
        )
        assert not executions
        print(
            json.dumps(
                {
                    "actor": "python",
                    "variant": "wait_expired_no_store",
                    "submission_id": reply["handle"]["submission_id"],
                    "provider_sends_delta": observed_count() - before,
                    "caller_tool_executions": len(executions),
                    "negative_stable_ms": stable_ms,
                    "candidate_access": status["candidate_access"],
                }
            )
        )


def malformed_provider_negative():
    with EzLLMRouterClient(
        os.environ["EZLLMROUTER_SERVICE_URL"], os.environ["EZLLMROUTER_DEV_TOKEN"]
    ) as client:
        before = observed_count()
        request = tool_request("step.dev03.malformed", "Use lookup for synthetic malformed.")
        try:
            client.submit(request, {"wait_ms": 3000})
        except EzLLMRouterError as exc:
            assert exc.code == "CANDIDATE_UNUSABLE" and exc.http_status == 502 and exc.handle
            handle = exc.handle
        else:
            raise AssertionError("malformed provider candidate accepted")
        stable_ms = stable_receiver_count(client, before + 1)
        status = client.getStatus({"submission_id": handle["submission_id"]})
        assert status["submission_state"] == "failed_after_transmit" and "candidate" not in status
        assert not executions
        print(
            json.dumps(
                {
                    "actor": "python",
                    "variant": "malformed_provider_negative",
                    "submission_id": handle["submission_id"],
                    "provider_sends_delta": 1,
                    "caller_tool_executions": 0,
                    "negative_stable_ms": stable_ms,
                    "failure": "CANDIDATE_UNUSABLE",
                }
            )
        )


def mutation_no_send_negative():
    with EzLLMRouterClient(
        os.environ["EZLLMROUTER_SERVICE_URL"], os.environ["EZLLMROUTER_DEV_TOKEN"]
    ) as client:
        before = observed_count()
        request = tool_request("step.dev03.mutation", "Use lookup for synthetic.")
        try:
            client.submit(request, {"wait_ms": 3000})
        except EzLLMRouterError as exc:
            assert exc.code == "FDC_REJECTED" and exc.http_status == 409 and exc.handle
            handle = exc.handle
        else:
            raise AssertionError("mutated prepared request dispatched")
        stable_ms = stable_receiver_count(client, before, duration=5.2)
        status = client.getStatus({"submission_id": handle["submission_id"]})
        assert status["submission_state"] == "failed_before_transmit" and "candidate" not in status
        assert not executions
        print(
            json.dumps(
                {
                    "actor": "python",
                    "variant": "tool_mutation_no_send",
                    "submission_id": handle["submission_id"],
                    "provider_sends_delta": 0,
                    "caller_tool_executions": 0,
                    "negative_stable_ms": stable_ms,
                    "failure": "FDC_REJECTED",
                }
            )
        )


def multi_call_cycle():
    with EzLLMRouterClient(
        os.environ["EZLLMROUTER_SERVICE_URL"], os.environ["EZLLMROUTER_DEV_TOKEN"]
    ) as client:
        before = observed_count()
        first = tool_request("step.dev03.multi", "Use two lookups for synthetic.")
        first_reply = receive(client, first)
        calls = first_reply["candidate"]["output_blocks"]
        assert [call["call_id"] for call in calls] == ["call.lookup.1", "call.lookup.2"]
        results = [lookup(call["arguments"]) for call in calls]
        second = json.loads(json.dumps(first))
        second["execution_generation"] = "gen.2"
        second["messages"].append({"role": "assistant", "blocks": calls})
        second["messages"].append(
            {
                "role": "tool",
                "blocks": [
                    {
                        "block_id": f"block.result.{i}",
                        "kind": "tool_result",
                        "call_id": call["call_id"],
                        "result_value": value,
                        "source_labels": RESULT_LABEL,
                    }
                    for i, (call, value) in enumerate(zip(calls, results, strict=True), 1)
                ],
            }
        )
        final_reply = receive(client, second)
        assert (
            final_reply["candidate"]["output_blocks"][0]["text"]
            == "Lookup pair: synthetic synthetic"
        )
        after = observed_count()
        assert after - before == 2 and len(executions) == 2
        print(
            json.dumps(
                {
                    "actor": "python",
                    "variant": "ordered_multi_call",
                    "first_submission_id": first_reply["handle"]["submission_id"],
                    "second_submission_id": final_reply["handle"]["submission_id"],
                    "provider_sends_delta": after - before,
                    "caller_tool_executions": len(executions),
                    "call_ids": [call["call_id"] for call in calls],
                }
            )
        )


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "cycle":
        cycle()
    elif len(sys.argv) == 2 and sys.argv[1] == "cycle_alt":
        cycle(alternative=True)
    elif len(sys.argv) in (3, 4) and sys.argv[1] == "status":
        status(sys.argv[2], sys.argv[3] if len(sys.argv) == 4 else "tool_call")
    elif len(sys.argv) == 5 and sys.argv[1] == "by_work":
        status_by_work(sys.argv[2], sys.argv[3], sys.argv[4])
    elif len(sys.argv) == 2 and sys.argv[1] == "text":
        text_regression()
    elif len(sys.argv) == 2 and sys.argv[1] == "no_store":
        no_store_cycle()
    elif len(sys.argv) == 2 and sys.argv[1] == "wait_no_store":
        wait_expiry_no_store()
    elif len(sys.argv) == 2 and sys.argv[1] == "malformed":
        malformed_provider_negative()
    elif len(sys.argv) == 2 and sys.argv[1] == "mutation":
        mutation_no_send_negative()
    elif len(sys.argv) == 2 and sys.argv[1] == "multi":
        multi_call_cycle()
    else:
        raise SystemExit(
            "usage: python_actor.py cycle | cycle_alt | no_store | wait_no_store | malformed | mutation | multi | status SUBMISSION_ID | text"
        )
