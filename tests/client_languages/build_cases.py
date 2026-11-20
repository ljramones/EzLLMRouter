"""Build shared native-client fixtures from maintained contracts and Python behavior.

Run with the repository's locked Python environment. Only injected transports run.
"""

from base64 import b64decode, b64encode
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from ezllmrouter_client import EzLLMRouterClient, IntegrationClient

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads((ROOT / path).read_text())


def digest(value):
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


class Response:
    def __init__(self, case):
        self.status_code = case.get("status", 200)
        self.headers = {
            "EzLLMRouter-Contract-Version": case.get("wire", "0.2"),
            "EzLLMRouter-Integration-Version": case.get("version", "1"),
            **case.get("response_headers", {}),
        }
        self.content = (
            b64decode(case["raw"])
            if "raw" in case
            else json.dumps(case["response"], ensure_ascii=False).encode()
        )

    def close(self):
        pass


class Transport:
    def __init__(self, case):
        self.case, self.calls = case, []

    def request(self, method, url, **kwargs):
        self.calls.append(
            {
                "method": method,
                "path": url.removeprefix("http://synthetic.invalid"),
                "headers": kwargs["headers"],
                "body": json.loads(kwargs["content"]) if "content" in kwargs else None,
            }
        )
        if self.case.get("lost"):
            raise OSError("synthetic lost response")
        return Response(self.case)


def evaluate(case):
    transport = Transport(case)
    cls = IntegrationClient if case.get("integration") else EzLLMRouterClient
    options = {"version": case.get("version", "1")} if case.get("integration") else {}
    with cls(
        "http://synthetic.invalid", "synthetic-token", transport=transport, **options
    ) as client:
        try:
            args = deepcopy(case.get("args", []))
            if "wait_ms" in case:
                args.append({"wait_ms": case["wait_ms"]})
            getattr(client, case["action"])(*args)
            expected = {"ok": True}
        except Exception as error:
            expected = {
                "code": getattr(error, "code", "SCHEMA_INVALID"),
                "retry_guidance": getattr(error, "retry_guidance", "never"),
                "http_status": getattr(error, "http_status", None) or 0,
                "selector": getattr(error, "selector", None),
                "handle": getattr(error, "handle", None),
            }
    expected["calls"] = transport.calls
    return expected


def cases():
    out = []
    legacy = read(
        "tests/fixtures/contracts/wp-a-03-c01/EZLLMROUTER-WP-A-VECTORS-v0.3-CORRECTION-01.json"
    )["examples"]
    successor = read("tests/fixtures/contracts/dev12-successor-01/vectors.json")
    request = legacy["submit_text"]
    selector = {
        key: request[key] for key in ("task_id", "step_id", "step_revision", "execution_generation")
    }

    def add(name, action, response, args=(), **fields):
        out.append(
            {
                "name": name,
                "action": action,
                "args": deepcopy(list(args)),
                "response": deepcopy(response),
                **deepcopy(fields),
            }
        )

    for name, value in legacy.items():
        if name.startswith("reply_"):
            status = (
                202
                if value["state"] == "pending"
                else 200
                if value["state"] == "delivered"
                else 409
            )
            add(name, "submit", value, [request], status=status, wait_ms=0)
        if name.startswith("status_") and "handle" in value:
            add(name, "get_status", value, [selector])
    add("capabilities", "get_capabilities", legacy["capabilities"])
    add(
        "status_by_id",
        "get_status",
        legacy["status_present"],
        [{"submission_id": "submission.demo"}],
    )
    add("submit_attributed", "submit_in_run", legacy["reply_delivered"], [request, "run.synthetic"])
    add("bad_wait", "submit", legacy["reply_delivered"], [request], wait_ms=30001)
    add("bad_selector", "get_status", legacy["status_present"], [{"submission_id": ""}])
    add("lost_ack", "submit", legacy["reply_delivered"], [request], lost=True)
    for name, text in (
        ("multiline", "Sure:\n1. item\n2. item"),
        ("escaped_text", "Columns:\tα\t🔐\r\nControl: \b\f\u0001\u007f"),
    ):
        response = deepcopy(legacy["reply_delivered"])
        response["candidate"]["output_blocks"][0]["text"] = text
        add(name + "_assistant", "submit", response, [request])
        status_reply = deepcopy(legacy["status_present"])
        status_reply["candidate"]["output_blocks"][0]["text"] = text
        add(name + "_status", "get_status", status_reply, [selector])
        multiline_request = deepcopy(request)
        multiline_request["messages"][-1]["blocks"][0]["text"] = text
        add(name + "_request", "submit", response, [multiline_request])
    tool = deepcopy(legacy["reply_tool"])
    tool["candidate"]["output_blocks"][0]["arguments"]["key"] = "line\nnext\tindent"
    add("multiline_tool_arguments", "submit", tool, [request])
    bad_id = deepcopy(request)
    bad_id["task_id"] += "\n"
    add("newline_identifier", "submit", legacy["reply_delivered"], [bad_id])
    bad_handle = deepcopy(legacy["reply_delivered"])
    bad_handle["handle"]["submission_id"] += "\n"
    add("newline_response_handle", "submit", bad_handle, [request])
    for name, mutation in (
        ("foreign_handle", {"task_id": "task.foreign"}),
        ("wrong_generation", {"execution_generation": "gen.foreign"}),
    ):
        response = deepcopy(legacy["reply_delivered"])
        response["handle"]["work_key"].update(mutation)
        add(name, "submit", response, [request])
    for label, raw in (
        ("duplicate_keys", b'{"contract_version":"0.2","state":"pending","state":"delivered"}'),
        ("bad_utf8", b"\xff"),
        ("unpaired_surrogate", b'{"x":"\\ud800"}'),
        ("unsafe_integer", b'{"x":9007199254740992}'),
        ("fraction", b'{"x":1.5}'),
        ("bom", b"\xef\xbb\xbf{}"),
        ("depth", b"[" * 34 + b"0" + b"]" * 34),
        ("control", b'{"x":"\\u0000"}'),
    ):
        add(label, "submit", {}, [request], raw=b64encode(raw).decode())
    add(
        "compressed",
        "submit",
        legacy["reply_delivered"],
        [request],
        response_headers={"Content-Encoding": "gzip"},
    )
    add("oversize", "submit", {}, [request], response_headers={"Content-Length": "20000000"})
    add("truncated", "submit", {}, [request], response_headers={"Content-Length": "500"})
    add(
        "wrong_version",
        "submit",
        legacy["reply_delivered"],
        [request],
        response_headers={"EzLLMRouter-Contract-Version": "0.3"},
    )
    add(
        "redirect",
        "submit",
        legacy["reply_delivered"],
        [request],
        status=307,
        response_headers={"Location": "https://foreign.invalid"},
    )
    rerank = next(x["request"] for x in successor["examples"] if x["id"] == "DELEGATED_RERANK")
    completed = next(x["value"] for x in successor["protocol_fixtures"] if x["id"] == "COMPLETED")
    for name, text in (("newline", "reason\n"), ("tab", "reason\tvalue")):
        bad_public = deepcopy(rerank)
        bad_public["input"]["query"] = text
        add(name + "_public_text", "submit_rerank", completed, [bad_public], wire="0.3")
    for fixture in successor["protocol_fixtures"]:
        value = fixture["value"]
        action = "get_successor_status" if fixture["id"].startswith("STATUS_") else "submit_rerank"
        args = (
            [{"submission_id": value["handle"]["submission_id"]}]
            if action.startswith("get_")
            else [rerank]
        )
        status = (
            409
            if value.get("state") == "failed"
            else 202
            if value.get("state") in ("pending", "outcome_unknown")
            else 200
        )
        add("successor_" + fixture["id"], action, value, args, wire="0.3", status=status)
    bad = deepcopy(completed)
    bad["result"]["results"][0]["candidate_id"] = "foreign.candidate"
    add("foreign_ranking", "submit_rerank", bad, [rerank], wire="0.3")
    bad = deepcopy(completed)
    bad["result"]["results"][0]["score"] = "99"
    add("invalid_score", "submit_rerank", bad, [rerank], wire="0.3")
    add(
        "successor_work_status",
        "get_successor_status",
        next(
            x["value"]
            for x in successor["protocol_fixtures"]
            if x["id"] == "STATUS_VALID_UNKNOWN_COST"
        ),
        [{"work_selector": rerank["work_selector"]}],
        wire="0.3",
    )
    embedding = next(x["request"] for x in successor["examples"] if x["id"] == "DIRECT_DOCUMENT")
    result = deepcopy(
        next(x["value"] for x in successor["result_examples"] if x["id"] == "EMBEDDING_RESULT")
    )
    response = deepcopy(completed)
    response["handle"]["work_key"].update(embedding["work_selector"])
    result["attempt_id"] = response["attempt_id"]
    response["result"] = result
    add("embedding", "submit_embedding", response, [embedding], wire="0.3")
    for version in ("1", "2", "3"):
        example = read(f"tests/fixtures/contracts/integration-readiness-v{version}/examples.json")
        if version == "3":
            previous = read("tests/fixtures/contracts/integration-readiness-v2/examples.json")
            example = {
                "dataset": previous["dataset"],
                "account": example["account"],
                "events": [example["start"], example["decision"]],
                "snapshots": [{**previous["snapshots"][0], "integration_version": "3"}],
            }
        base = {"integration_version": version}
        for action, key in (("create_dataset", "dataset"), ("register_account", "account")):
            add(
                f"v{version}_{action}",
                action,
                base,
                [example[key]],
                integration=True,
                version=version,
                status=201,
            )
        dataset_id, account_id = example["dataset"]["dataset_id"], example["account"]["account_id"]
        for index, event in enumerate(example["events"]):
            receipt = {
                **base,
                "dataset_id": event["dataset_id"],
                "event_id": event["event_id"],
                "kind": event["kind"],
                "event_digest": digest(event),
                "membership_at_receipt": "included",
            }
            add(
                f"v{version}_event_{index}",
                "submit_observation",
                receipt,
                [event],
                integration=True,
                version=version,
                status=201,
            )
            if index == 0:
                add(
                    f"v{version}_receipt",
                    "recover_receipt",
                    receipt,
                    [event["dataset_id"], event["event_id"]],
                    integration=True,
                    version=version,
                )
                foreign = {**receipt, "event_digest": "sha256:" + "0" * 64}
                add(
                    f"v{version}_foreign_digest",
                    "submit_observation",
                    foreign,
                    [event],
                    integration=True,
                    version=version,
                )
        for index, snap in enumerate(example.get("snapshots", [])):
            reply = {**base, "snapshot_id": snap["snapshot_id"], "snapshot_digest": digest(snap)}
            add(
                f"v{version}_snapshot_{index}",
                "submit_snapshot",
                reply,
                [snap],
                integration=True,
                version=version,
            )
            add(
                f"v{version}_snapshot_read_{index}",
                "snapshot",
                base,
                [dataset_id, snap["snapshot_id"]],
                integration=True,
                version=version,
            )
        add(
            f"v{version}_state",
            "set_account_state",
            base,
            [account_id, {"dataset_id": dataset_id, "state": "disabled", "expected_revision": 1}],
            integration=True,
            version=version,
        )
        add(f"v{version}_report", "report", base, [dataset_id], integration=True, version=version)
        if version != "1":
            add(
                f"v{version}_export",
                "export_dataset",
                base,
                [dataset_id],
                integration=True,
                version=version,
            )
        reply = {
            **base,
            "dataset_id": dataset_id,
            "account_id": account_id,
            "model_id": "model.synthetic",
            "account_revision": 1,
            "usable": True,
            "reason": "usable",
        }
        if version != "1":
            reply.update(eligibility_id="elig.synthetic", evaluated_at="2026-11-19T00:00:00Z")
        if version == "3":
            reply.update(
                operation_family="generation",
                capability="generation",
                selection_kind="known_model",
                provider_id="provider.synthetic",
                credential_ref="manager.synthetic",
            )
        if version != "1":
            reply["eligibility_digest"] = digest(reply)
        add(
            f"v{version}_eligibility",
            "eligibility",
            reply,
            [dataset_id, account_id, "model.synthetic"],
            integration=True,
            version=version,
        )
        if version == "3":
            selector = {
                "operation_family": "speech_input",
                "capability": "transcription",
                "selection_kind": "provider_selected",
            }
            speech = {**reply, **selector}
            speech.pop("model_id")
            speech.pop("eligibility_digest")
            speech["eligibility_digest"] = digest(speech)
            add(
                "v3_speech_eligibility",
                "operation_eligibility",
                speech,
                [dataset_id, account_id, selector],
                integration=True,
                version=version,
            )
            add(
                "v3_permissions",
                "set_account_permissions",
                base,
                [
                    account_id,
                    {
                        "dataset_id": dataset_id,
                        "expected_revision": 1,
                        "allowed_models": [],
                        "allowed_operations": [],
                    },
                ],
                integration=True,
                version=version,
            )
    run = {
        "version": "1",
        "run_id": "run.synthetic",
        "task_id": "task.demo",
        "task_class": "class.demo",
        "evaluation_ref": "rubric.v1",
        "mode": "direct_human",
    }
    stored = {key: value for key, value in run.items() if key != "version"}
    stored.update(
        principal_id="user.synthetic",
        charging_owner_id="owner.synthetic",
        initiating_user_id="user.synthetic",
        agent_id=None,
        agent_version=None,
        parent_run_id=None,
        root_run_id=run["run_id"],
        created_at="2026-11-19T00:00:00Z",
        status="running",
        request_digest="sha256:" + "a" * 64,
    )
    envelope = {"contract_version": "0.2", "attribution_version": "1", "run": stored}
    add("start_run", "start_run", envelope, [run])
    add("get_run", "get_run", envelope, [run["run_id"]])
    event = {
        "version": "1",
        "event_id": "outcome.synthetic",
        "run_id": run["run_id"],
        "kind": "task_outcome",
        "subject_revision": 1,
        "verdict": "accepted",
        "evaluator_version": "rubric.v1",
        "evidence_ref": "evidence.synthetic",
    }
    receipt = {
        key: event[key] for key in ("version", "event_id", "run_id", "kind", "subject_revision")
    }
    receipt.update(recorded_at="2026-11-19T00:00:00Z", event_digest=digest(event))
    envelope = {"contract_version": "0.2", "outcome_version": "1", "receipt": receipt}
    add("report_outcome", "report_outcome", envelope, [event], status=201)
    add("recover_outcome", "get_outcome_receipt", envelope, [event["event_id"]])
    null_request = deepcopy(request)
    null_request["unserializable_null"] = None
    add("null_request_value", "submit", legacy["reply_delivered"], [null_request])
    for label, control in (
        ("newline", "\n"),
        ("tab", "\t"),
        ("carriage_return", "\r"),
        ("delete", "\x7f"),
    ):
        bad_reason = deepcopy(rerank)
        bad_reason["metadata"]["commission"]["declared_reason"] = "reason" + control
        add(label + "_declared_reason", "submit_rerank", completed, [bad_reason], wire="0.3")
    error_reply = {
        "contract_version": "0.2",
        "error": {
            "code": "POLICY_DENIED",
            "correlation_id": "corr.test",
            "retry_guidance": "never",
        },
    }
    add("attribution_error_with_success_status", "get_run", error_reply, [run["run_id"]])
    add(
        "server_internal_error_preserved",
        "get_capabilities",
        {
            "contract_version": "0.2",
            "error": {
                "code": "INTERNAL_UNAVAILABLE",
                "correlation_id": "corr.test",
                "retry_guidance": "query_first",
            },
        },
        status=503,
    )
    for version in ("1", "2", "3"):
        add(
            f"v{version}_newline_dataset",
            "report",
            {"integration_version": version},
            ["dataset.bad\n"],
            integration=True,
            version=version,
        )
        for label, guidance in (
            ("missing", None),
            ("invalid", "retry_anything"),
            ("explicit_never", "never"),
        ):
            error = {"code": "INTERNAL_UNAVAILABLE"}
            if guidance is not None:
                error["retry_guidance"] = guidance
            add(
                f"v{version}_503_{label}_guidance",
                "report",
                {"integration_version": version, "error": error},
                ["dataset.test"],
                integration=True,
                version=version,
                status=503,
            )
    for case in out:
        case["expected"] = evaluate(case)
    return out


if __name__ == "__main__":
    value = cases()
    (HERE / "cases.json").write_text(json.dumps(value, ensure_ascii=True, indent=2) + "\n")
    print(f"Wrote {len(value)} shared client cases")
