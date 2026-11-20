"""Populated, authenticated operator and preserving-migration target cases.

Import is deliberately inert and stdlib-only for the no-send host preflight.
All requests and storage work happen inside a selected case, after release.
"""

from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import csv
import io
import json
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlencode

from dev12_completion_catalog import CaseHandler


SOURCE = Path(__file__).resolve()


def _retained(runtime, case, stages, checks, payload):
    """Keep actual observation bytes and each distinct objective result."""
    if set(checks) != set(case["predicates"]):
        raise AssertionError("operator handler omitted an objective")
    if not all(
        type(value) is tuple
        and len(value) == 2
        and type(value[0]) is bool
        and type(value[1]) is str
        and value[1]
        for value in checks.values()
    ):
        raise AssertionError("operator objective result invalid")
    path = runtime.root / "cases" / (case["id"] + ".json")
    path.parent.mkdir(exist_ok=True)
    document = {
        "case_id": case["id"],
        "scenario_id": case["scenario_id"],
        "variant": case["variant"],
        "attempt_group": case["attempt_group"],
        "stages": stages,
        "checks": {
            name: {"passed": passed, "detail": detail} for name, (passed, detail) in checks.items()
        },
        "payload": payload,
    }
    raw = (json.dumps(document, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()
    if len(raw) > 1_000_000:
        raise AssertionError("operator case evidence exceeds bound")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        import os

        os.fsync(stream.fileno())
    relative = str(path.relative_to(runtime.root))
    digest = sha256(raw).hexdigest()
    observations = [
        {
            "stage": stage,
            "evidence_path": relative,
            "sha256": digest,
            "case_id": case["id"],
            "attempt_group": case["attempt_group"],
            "observed": value,
        }
        for stage, value in stages.items()
    ]
    assertions = [
        {
            "id": name,
            "passed": passed,
            "executed": True,
            "evidence_paths": [relative],
            "detail": detail,
        }
        for name, (passed, detail) in checks.items()
    ]
    return {
        "status": "PASS" if all(item["passed"] for item in assertions) else "FAIL",
        "observations": observations,
        "assertions": assertions,
    }


def _census(runtime):
    with runtime.store._lock:
        submissions = runtime.store.db.execute("SELECT COUNT(*) FROM dev12_submissions").fetchone()[
            0
        ]
        usage = runtime.store.db.execute("SELECT COUNT(*) FROM dev12_usage_revisions").fetchone()[0]
    arrivals = len(
        (runtime.receiver_log.read_bytes().splitlines() if runtime.receiver_log.exists() else [])
    )
    allowance = runtime.allowance.inspect()
    return {
        "submissions": submissions,
        "usage_revisions": usage,
        "receiver_arrivals": arrivals,
        "attempt_count": allowance["attempt_count"],
        "possible_send_count": allowance["possible_send_count"],
    }


@contextmanager
def _operator_client(runtime, actor="owner"):
    import httpx

    credential = getattr(runtime, "operator_credentials", {}).get(actor)
    if type(credential) is not str:
        raise RuntimeError("disposable authenticated operator principal unavailable")
    client = httpx.Client(
        base_url=runtime.operator_url,
        timeout=10,
        trust_env=False,
        headers={"Origin": runtime.operator_url},
    )
    with client:
        response = client.post("/operator/v1/login", json={"password": credential})
        if response.status_code != 200:
            raise AssertionError(f"{actor} operator login failed: HTTP {response.status_code}")
        yield client


def _read(client, filters=None, export=None):
    params = dict(filters or {})
    if export is not None:
        params["export"] = export
    url = "/operator/v1/dev12-usage" + ("?" + urlencode(params) if params else "")
    response = client.get(url)
    if response.status_code != 200:
        return {"status": response.status_code, "body": response.text[:2000]}
    if export == "csv":
        return {
            "status": 200,
            "rows": list(csv.DictReader(io.StringIO(response.text))),
            "content_type": response.headers.get("Content-Type"),
        }
    return {"status": 200, "report": response.json()}


def _known_sum(rows):
    return sum(
        (
            Decimal(row["amount_decimal"])
            for row in rows
            if row["cost_status"] in {"calculated", "over_bound"}
        ),
        Decimal(0),
    )


def _csv_finance_reconcile(csv_rows, json_rows, total):
    """Compare independent CSV fields and Decimal amounts for each attempt."""
    by_csv = {row["attempt_id"]: row for row in csv_rows}
    by_json = {row["attempt_id"]: row for row in json_rows}
    if (
        len(by_csv) != len(csv_rows)
        or len(by_json) != len(json_rows)
        or set(by_csv) != set(by_json)
    ):
        return False, {"reason": "attempt identity mismatch"}
    fields = ("cost_status", "currency", "exposure_state", "candidate_access", "delivery_state")
    for attempt_id, csv_row in by_csv.items():
        json_row = by_json[attempt_id]
        if (
            any(csv_row[field] != json_row[field] for field in fields)
            or csv_row["usage_revision"]
            != ("" if json_row["usage_revision"] is None else str(json_row["usage_revision"]))
            or csv_row["amount_decimal"]
            != ("" if json_row["amount_decimal"] is None else str(json_row["amount_decimal"]))
        ):
            return False, {"reason": "financial row mismatch", "attempt_id": attempt_id}
        if csv_row["cost_status"] in {"unknown", "not_sent"} and csv_row["amount_decimal"] != "":
            return False, {"reason": "unobserved amount manufactured", "attempt_id": attempt_id}
    csv_known = _known_sum(csv_rows)
    json_known = _known_sum(json_rows)
    exact = (
        csv_known == json_known == Decimal(total["known_usd"])
        and sum(row["cost_status"] in {"calculated", "over_bound"} for row in csv_rows)
        == total["known_attempts"]
        and sum(row["cost_status"] == "not_sent" for row in csv_rows) == total["not_sent_attempts"]
        and sum(row["cost_status"] == "unknown" for row in csv_rows)
        == total["unknown_cost_attempts"]
    )
    return exact, {
        "csv_known_usd": str(csv_known),
        "json_known_usd": str(json_known),
        "csv_attempts": len(csv_rows),
        "json_attempts": len(json_rows),
    }


def _same_census(before, after):
    return before == after


def _browser_attestation(runtime, name, report):
    """Verify independent browser capture bytes before using its observations."""
    path = runtime.root / name
    if not path.is_file() or path.is_symlink():
        raise AssertionError(f"independent browser evidence absent: {name}")
    value = json.loads(path.read_text())
    expected = {
        "kind",
        "campaign_id",
        "source_tree",
        "operator_url",
        "browser_url",
        "port_forward",
        "target_probe",
        "capture_source",
        "capture_source_sha256",
        "screenshots",
        "browser",
        "ledger_before",
        "ledger_after",
        "local_get_count",
    }
    if (
        type(value) is not dict
        or set(value) != expected
        or value["kind"] != "dev12_controlled_browser_observation_v1"
        or value["campaign_id"] != runtime.plan["envelope"]["campaign_id"]
        or value["source_tree"] != runtime.plan["source_tree"]
        or value["operator_url"] != runtime.operator_url
        or type(value["browser_url"]) is not str
        or not value["browser_url"].startswith("http://127.0.0.1:")
        or type(value["local_get_count"]) is not int
        or value["local_get_count"] < 1
        or type(value["browser"]) is not dict
        or value["ledger_before"] != value["ledger_after"]
    ):
        raise AssertionError("browser evidence identity, read count or no-send baseline invalid")
    census = _census(runtime)
    ledger = value["ledger_after"]
    counters = (
        "submissions",
        "usage_revisions",
        "receiver_arrivals",
        "attempt_count",
        "possible_send_count",
    )
    if (
        type(ledger) is not dict
        or set(ledger) != {*counters, "files"}
        or any(type(ledger[key]) is not int or ledger[key] != census[key] for key in counters)
        or type(ledger["files"]) is not dict
        or set(ledger["files"])
        != {"receiver.jsonl", "guard.jsonl", "send-events.jsonl", "receiver-receipts.jsonl"}
    ):
        raise AssertionError("browser ledger baseline lacks the live target census")
    for filename, retained in ledger["files"].items():
        file = runtime.root / filename
        if file.is_symlink():
            raise AssertionError("browser ledger file is a symlink")
        present = file.is_file()
        actual = file.read_bytes() if present else b""
        if (
            type(retained) is not dict
            or set(retained) != {"present", "bytes", "sha256"}
            or retained
            != {
                "present": present,
                "bytes": len(actual),
                "sha256": sha256(actual).hexdigest() if present else None,
            }
        ):
            raise AssertionError("browser ledger file identity differs from current target")
    from dev12_completion_preflight import mounted_source_identity

    attempt_digest = sha256(
        "\n".join(sorted(row["attempt_id"] for row in report["attempts"])).encode()
    ).hexdigest()
    probe = value["target_probe"]
    if (
        type(probe) is not dict
        or set(probe) != {"build_fingerprint", "report_attempt_ids_sha256", "report_total"}
        or probe["build_fingerprint"] != mounted_source_identity()["sha256"]
        or probe["report_attempt_ids_sha256"] != attempt_digest
        or probe["report_total"] != report["total"]
    ):
        raise AssertionError("browser target probe differs from current authenticated operator")
    mapping = value["port_forward"]
    if value["browser_url"] == runtime.operator_url:
        if mapping is not None:
            raise AssertionError("unneeded browser port mapping asserted")
    else:
        if (
            type(mapping) is not dict
            or set(mapping) != {"from", "to", "method", "evidence_path", "sha256"}
            or mapping["from"] != runtime.operator_url
            or mapping["to"] != value["browser_url"]
            or mapping["method"] != "local_port_forward"
        ):
            raise AssertionError("browser URL lacks exact local port-forward mapping")
        supplied = Path(mapping["evidence_path"])
        mapped = (supplied if supplied.is_absolute() else runtime.root / supplied).resolve(
            strict=True
        )
        if (
            not mapped.is_relative_to(runtime.root)
            or not mapped.is_file()
            or sha256(mapped.read_bytes()).hexdigest() != mapping["sha256"]
        ):
            raise AssertionError("browser local mapping evidence unavailable")
    root = Path(__file__).resolve().parents[2]
    supplied = Path(value["capture_source"])
    source = (supplied if supplied.is_absolute() else root / supplied).resolve(strict=True)
    if (
        not source.is_relative_to(root)
        or not source.is_file()
        or sha256(source.read_bytes()).hexdigest() != value["capture_source_sha256"]
    ):
        raise AssertionError("browser capture source identity differs")
    screenshots = value["screenshots"]
    if type(screenshots) is not list or not screenshots:
        raise AssertionError("browser screenshots absent")
    for row in screenshots:
        if type(row) is not dict or set(row) != {"path", "sha256"}:
            raise AssertionError("browser screenshot identity malformed")
        supplied = Path(row["path"])
        file = (supplied if supplied.is_absolute() else runtime.root / supplied).resolve(
            strict=True
        )
        if (
            not file.is_relative_to(runtime.root)
            or not file.is_file()
            or file.suffix != ".png"
            or sha256(file.read_bytes()).hexdigest() != row["sha256"]
        ):
            raise AssertionError("browser screenshot missing or changed")
    return value, sha256(path.read_bytes()).hexdigest()


def operator_identity(runtime, case):
    """Three real synthetic identities and two pre-admission forged controls."""
    if (case["scenario_id"], case["variant"]) != ("t60", "composed"):
        raise NotImplementedError("unsupported operator identity case")
    from dev12_completion_handlers import _case_request, _headers, _post
    from ezllmrouter_server.successor_contract import classify_request

    before = _census(runtime)
    positives = {}
    for vector in ("DIRECT_DOCUMENT", "DELEGATED_RERANK", "AUTONOMOUS_QUERY"):
        request = _case_request(runtime, case, vector)
        result = _post(runtime, request, _headers(runtime, vector))
        positives[vector] = result
    after_positive = _census(runtime)
    delegated = _case_request(runtime, case, "DELEGATED_RERANK")
    forged_agent = deepcopy(delegated)
    forged_agent["work_selector"]["step_id"] += ".forged.agent"
    forged_agent["metadata"]["run_id"] = "run.forged.agent"
    forged_owner = deepcopy(delegated)
    forged_owner["work_selector"]["step_id"] += ".forged.owner"
    forged_owner["charging_owner_id"] = "team.forged"
    forged_delegation = deepcopy(delegated)
    forged_delegation["work_selector"]["step_id"] += ".forged.delegation"
    forged_delegation["metadata"]["delegation"][-1]["to_actor_id"] = "agent.forged"
    cyclic = deepcopy(delegated)
    cyclic["work_selector"]["step_id"] += ".cycle"
    cyclic["metadata"]["delegation"][-1]["to_actor_id"] = "user.demo"
    context = runtime.contexts_by_credential[runtime.credentials["DELEGATED_RERANK"]]
    negatives_requests = (forged_agent, forged_owner, forged_delegation, cyclic)
    classifications = [classify_request(value, context) for value in negatives_requests]
    if classifications != [
        "SEMANTIC_INVALID",
        "SCHEMA_INVALID",
        "SEMANTIC_INVALID",
        "SEMANTIC_INVALID",
    ]:
        raise AssertionError(
            "forged/cyclic ingress fixture unexpectedly eligible; no negative sent"
        )
    negatives = [
        _post(runtime, value, _headers(runtime, "DELEGATED_RERANK")) for value in negatives_requests
    ]
    after = _census(runtime)
    with _operator_client(runtime) as client:
        report_result = _read(client)
    report = report_result.get("report", {})
    rows = report.get("attempts", [])
    by_actor = {row["actor_id"]: row for row in rows}
    direct = by_actor.get("user.demo", {})
    delegated_row = by_actor.get("agent.vega", {})
    autonomous = by_actor.get("svc.orion", {})
    positive_ok = all(
        value["http_status"] in (200, 202)
        and value["status"]
        and value["status"].get("submission_state") == "completed"
        for value in positives.values()
    )
    checks = {
        "t60.direct_human": (
            bool(
                positive_ok
                and direct.get("initiating_user_id") == "user.demo"
                and direct.get("actor_id") == "user.demo"
            ),
            "Direct human kept its own actor and initiating-user identity",
        ),
        "t60.delegated_agent": (
            bool(
                positive_ok
                and delegated_row.get("initiating_user_id") == "user.demo"
                and delegated_row.get("parent_run_id") == "run.bud"
            ),
            "Delegated agent retained human initiator and distinct parent run",
        ),
        "t60.autonomous": (
            bool(
                positive_ok
                and autonomous.get("initiating_user_id") is None
                and autonomous.get("actor_id") == "svc.orion"
            ),
            "Autonomous service retained no fictitious initiating person",
        ),
        "t60.forged_agent": (
            bool(
                classifications[0] == "SEMANTIC_INVALID"
                and negatives[0]["http_status"] >= 400
                and after["submissions"] == after_positive["submissions"]
            ),
            "Caller-forged agent run rejected against trusted authenticated run",
        ),
        "t60.forged_owner": (
            bool(
                classifications[1] == "SCHEMA_INVALID"
                and negatives[1]["http_status"] >= 400
                and after["submissions"] == after_positive["submissions"]
            ),
            "Caller-supplied charging-owner field rejected; owner remains trusted",
        ),
        "t60.forged_delegation": (
            bool(
                classifications[2] == "SEMANTIC_INVALID"
                and negatives[2]["http_status"] >= 400
                and after["submissions"] == after_positive["submissions"]
            ),
            "Forged final delegation endpoint rejected before admission",
        ),
        "t60.cycle": (
            bool(
                classifications[3] == "SEMANTIC_INVALID"
                and negatives[3]["http_status"] >= 400
                and after["receiver_arrivals"] == after_positive["receiver_arrivals"]
                and after_positive["receiver_arrivals"] == before["receiver_arrivals"] + 3
            ),
            "Cyclic delegation rejected without another receiver arrival",
        ),
    }
    stages = {
        "operator": {
            "report_attempts": len(rows),
            "actors": sorted(by_actor),
            "negative_http": [value["http_status"] for value in negatives],
        }
    }
    return _retained(
        runtime,
        case,
        stages,
        checks,
        {
            "positive": positives,
            "negative": negatives,
            "classifications": classifications,
            "before": before,
            "after_positive": after_positive,
            "after": after,
            "selected_rows": [direct, delegated_row, autonomous],
        },
    )


def operator_reporting(runtime, case):
    """Authenticated HTTP reporting, exact unique-attempt and filter checks."""
    if case["variant"] != "composed" or case["scenario_id"] not in {
        "t61",
        "t62_a",
        "t62_b",
        "t62_c",
        "t62_d",
        "t62_e",
        "t64",
        "t65",
    }:
        raise NotImplementedError("unsupported operator report case")
    scenario = case["scenario_id"]
    correction = None
    if scenario == "t62_b":
        from dev12_completion_handlers import _trusted

        historical_before = _census(runtime)
        with runtime.store._lock:
            candidates = runtime.store.db.execute(
                "SELECT submission_id,record FROM dev12_submissions WHERE "
                "json_extract(record,'$.work_key.step_id')=?",
                ("step.completion02.t49.e.composed.late",),
            ).fetchall()
            if len(candidates) != 1:
                raise AssertionError("unique retained historical correction absent")
            cutoff_submission, record_raw = candidates[0]
            record = json.loads(record_raw)
            old_row = runtime.store.db.execute(
                "SELECT usage FROM dev12_usage_revisions WHERE attempt_id=? AND revision=2",
                (record["attempt_id"],),
            ).fetchone()
            old_event = runtime.store.db.execute(
                "SELECT observed_at FROM dev12_evidence_events WHERE submission_id=? "
                "AND event_kind='native_usage_accepted' AND "
                "json_extract(evidence,'$.revision')=2 ORDER BY event_id",
                (cutoff_submission,),
            ).fetchall()
        if old_row is None or len(old_event) != 1 or record.get("effective_usage_revision") != 2:
            raise AssertionError("accepted historical revision two absent")
        old_usage = json.loads(old_row[0])
        if old_usage.get("cost_status") != "calculated":
            raise AssertionError("historical known usage required")
        # This is a same-amount re-adjudication of the retained observation,
        # not a new measurement, admission, reservation or sender invocation.
        next_usage = deepcopy(old_usage)
        next_usage["revision"] = 3
        next_usage["previous_revision"] = 2
        cutoff_at = old_event[0][0]
        deadline = time.monotonic() + 3
        while (
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") <= cutoff_at
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        if datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") <= cutoff_at:
            raise AssertionError("distinct UTC cutoff second unavailable")
        outcome = runtime.successor.ingest_usage_revision(
            cutoff_submission, next_usage, _trusted(runtime)
        )
        historical_after = _census(runtime)
        corrected = runtime.successor.status(cutoff_submission, _trusted(runtime))
        correction = {
            "submission_id": cutoff_submission,
            "attempt_id": record["attempt_id"],
            "outcome": outcome,
            "before": historical_before,
            "after": historical_after,
            "status": corrected,
        }
        if (
            outcome != "accepted"
            or corrected["attempts"][0]["usage_revision"] != next_usage
            or historical_after["usage_revisions"] != historical_before["usage_revisions"] + 1
            or any(
                historical_after[key] != historical_before[key]
                for key in (
                    "submissions",
                    "receiver_arrivals",
                    "attempt_count",
                    "possible_send_count",
                )
            )
        ):
            raise AssertionError("historical re-adjudication changed send or charge basis")
    before = _census(runtime)
    with _operator_client(runtime) as client:
        full_result = _read(client)
        full = full_result.get("report", {})
        rows = full.get("attempts", [])
        if not rows:
            raise AssertionError("populated operator report required")
        if scenario == "t61":
            demo_response = client.get(
                "/operator/v1/demo-workspace?collection=expanded&story=expanded_all"
            )
            demo = demo_response.json() if demo_response.status_code == 200 else {}
            demo_actors = {item["id"]: item for item in demo.get("actors", [])}
            synthetic_noncharges = {"demo.agent.idle", "demo.agent.uninstrumented"}
            demo_attempt_actors = {item["actor"] for item in demo.get("attempts", [])}
            groupings = full["groupings"]
            known = _known_sum(rows)

            def groups_exact(name):
                actual = {item["id"]: item for item in groupings[name]}
                expected = {}
                for item in rows:
                    expected.setdefault(item[name] or "__absent__", []).append(item)
                return set(actual) == set(expected) and all(
                    actual[key]["attempts"] == len(members)
                    and Decimal(actual[key]["known_usd"]) == _known_sum(members)
                    for key, members in expected.items()
                )

            groups_ok = all(
                groups_exact(name) for name in ("actor_id", "provider_ref", "initiating_user_id")
            )
            workflows = full["workflows"]

            def scope_for(item):
                return (
                    item.get("initiating_user_id") or item.get("principal_id"),
                    item["task_id"],
                    item["root_workflow_id"],
                )

            parents = {
                (
                    item["initiating_or_autonomous_principal_id"],
                    item["task_id"],
                    item["root_workflow_id"],
                    item["run_id"],
                ): item["parent_run_id"]
                for item in workflows
            }

            def descends(row, workflow):
                if scope_for(row) != (
                    workflow["initiating_or_autonomous_principal_id"],
                    workflow["task_id"],
                    workflow["root_workflow_id"],
                ):
                    return False
                current, seen = row["run_id"], set()
                while current and current not in seen:
                    if current == workflow["run_id"]:
                        return True
                    seen.add(current)
                    current = parents.get((*scope_for(row), current))
                return False

            inclusive_ok = all(
                item["direct"]["attempts"]
                == sum(
                    row["run_id"] == item["run_id"]
                    and scope_for(row)
                    == (
                        item["initiating_or_autonomous_principal_id"],
                        item["task_id"],
                        item["root_workflow_id"],
                    )
                    for row in rows
                )
                and Decimal(item["direct"]["known_usd"])
                == _known_sum(
                    [
                        row
                        for row in rows
                        if row["run_id"] == item["run_id"]
                        and scope_for(row)
                        == (
                            item["initiating_or_autonomous_principal_id"],
                            item["task_id"],
                            item["root_workflow_id"],
                        )
                    ]
                )
                and item["total_including_delegated"]["attempts"]
                == sum(descends(row, item) for row in rows)
                and Decimal(item["total_including_delegated"]["known_usd"])
                == _known_sum([row for row in rows if descends(row, item)])
                for item in workflows
            )
            statuses = {row["cost_status"] for row in rows}
            unknown_view = full_result
            if "unknown" not in statuses:
                with runtime.store._lock:
                    candidates = [
                        (json.loads(raw), at)
                        for raw, at in runtime.store.db.execute(
                            "SELECT evidence,observed_at FROM dev12_evidence_events "
                            "WHERE event_kind='native_usage_accepted' ORDER BY event_id"
                        )
                    ]
                cutoff = next(
                    (
                        at
                        for usage, at in candidates
                        if usage.get("revision") == 1 and usage.get("cost_status") == "unknown"
                    ),
                    None,
                )
                if cutoff:
                    unknown_view = _read(client, {"cutoff": cutoff})
            unknown_report = unknown_view.get("report", {})
            unknown_rows = [
                item
                for item in unknown_report.get("attempts", [])
                if item["cost_status"] == "unknown"
            ]
            checks = {
                "t61.direct_inclusive": (
                    bool(
                        inclusive_ok
                        and workflows
                        and len({row["attempt_id"] for row in rows}) == len(rows)
                    ),
                    "Each direct attempt appears once; inclusive lineage does not shrink below direct",
                ),
                "t61.provider_person": (
                    groups_ok and known == Decimal(full["total"]["known_usd"]),
                    "Actor, provider and initiating-person group totals each reconcile to unique attempts",
                ),
                "t61.unknown_uninstrumented_idle": (
                    bool(
                        unknown_rows
                        and unknown_report.get("total", {}).get("unknown_cost_attempts", 0) > 0
                        and synthetic_noncharges.issubset(demo_actors)
                        and not synthetic_noncharges.intersection(demo_attempt_actors)
                        and demo_actors["demo.agent.idle"].get("coverage") == "No activity recorded"
                        and demo_actors["demo.agent.uninstrumented"].get("coverage")
                        == "Not measured"
                    ),
                    "Unknown charged attempt, idle demo actor and uninstrumented demo actor remain distinct",
                ),
            }
            selected = {
                "total": full["total"],
                "groupings": groupings,
                "workflows": workflows,
                "cost_statuses": sorted(statuses),
                "unknown_cutoff_view": unknown_view,
                "demo_noncharge_actors": [
                    demo_actors.get(name) for name in sorted(synthetic_noncharges)
                ],
                "demo_http_status": demo_response.status_code,
            }
        elif scenario == "t62_a":
            first = sorted(rows, key=lambda row: row["created_at"])[0]
            start = first["created_at"]
            end = (
                datetime.fromisoformat(start.replace("Z", "+00:00")) + timedelta(seconds=1)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            selected = {
                "at_start": _read(client, {"from": start, "to": end}),
                "before_start": _read(client, {"to": start}),
                "at_end": _read(client, {"from": end}),
                "offset_rejected": _read(client, {"from": start.replace("Z", "+00:00")}),
            }
            at_start = selected["at_start"].get("report", {}).get("attempts", [])
            before_start = selected["before_start"].get("report", {}).get("attempts", [])
            at_end = selected["at_end"].get("report", {}).get("attempts", [])
            checks = {
                "t62_a.period_boundary": (
                    bool(
                        first["attempt_id"] in {row["attempt_id"] for row in at_start}
                        and first["attempt_id"]
                        not in {row["attempt_id"] for row in before_start + at_end}
                    ),
                    "From includes its UTC second; to excludes its UTC second",
                ),
                "t62_a.timezone_boundary": (
                    selected["offset_rejected"]["status"] == 400,
                    "Noncanonical offset timestamp is rejected rather than shifted silently",
                ),
            }
        elif scenario == "t62_b":
            with runtime.store._lock:
                events = [
                    (sid, json.loads(raw), at)
                    for sid, raw, at in runtime.store.db.execute(
                        "SELECT submission_id,evidence,observed_at FROM dev12_evidence_events "
                        "WHERE event_kind='native_usage_accepted' AND submission_id=? "
                        "ORDER BY event_id",
                        (cutoff_submission,),
                    )
                ]
            pair = None
            for sid, usage, at in events:
                if usage.get("revision") == 3:
                    prior = next(
                        (
                            (p_usage, p_at)
                            for p_sid, p_usage, p_at in events
                            if p_sid == sid and p_usage.get("revision") == 2
                        ),
                        None,
                    )
                    if prior and prior[1] < at:
                        pair = (sid, prior[0], prior[1], usage, at)
                        break
            if pair is None:
                raise AssertionError("two accepted revisions at distinct UTC seconds required")
            sid, early_usage, early_at, late_usage, late_at = pair
            early = _read(client, {"cutoff": early_at})
            late = _read(client, {"cutoff": late_at})
            early_row = next(
                (
                    row
                    for row in early.get("report", {}).get("attempts", [])
                    if row["submission_id"] == sid
                ),
                {},
            )
            late_row = next(
                (
                    row
                    for row in late.get("report", {}).get("attempts", [])
                    if row["submission_id"] == sid
                ),
                {},
            )
            selected = {
                "submission_id": sid,
                "attempt_id": correction["attempt_id"],
                "controlled_correction": {
                    "kind": "same-amount historical re-adjudication",
                    "outcome": correction["outcome"],
                    "receiver_arrivals_delta": correction["after"]["receiver_arrivals"]
                    - correction["before"]["receiver_arrivals"],
                    "possible_sends_delta": correction["after"]["possible_send_count"]
                    - correction["before"]["possible_send_count"],
                },
                "early_at": early_at,
                "late_at": late_at,
                "early_usage": early_usage,
                "late_usage": late_usage,
                "early_row": early_row,
                "late_row": late_row,
            }
            checks = {
                "t62_b.revision_cutoff": (
                    bool(
                        early_row.get("usage_revision") == 2
                        and late_row.get("usage_revision") == 3
                        and early_row.get("attempt_id")
                        == late_row.get("attempt_id")
                        == correction["attempt_id"]
                        and early_usage["amount_decimal"] == late_usage["amount_decimal"]
                        and correction["outcome"] == "accepted"
                        and correction["after"]["receiver_arrivals"]
                        == correction["before"]["receiver_arrivals"]
                    ),
                    "UTC cutoff selects accepted revisions two and three without another send or charge",
                )
            }
        elif scenario == "t62_c":
            row = rows[0]
            if row.get("environment") != "standalone-synthetic":
                raise AssertionError("fixed synthetic environment missing from populated report")
            keys = {
                "provider_filter": ("provider_ref", row["provider_ref"]),
                "actor_filter": ("actor_id", row["actor_id"]),
                "task_filter": ("task_id", row["task_id"]),
                "environment_filter": ("environment", row["environment"]),
            }
            selected = {name: _read(client, {key: value}) for name, (key, value) in keys.items()}
            checks = {
                f"t62_c.{name}": (
                    bool(
                        result["status"] == 200
                        and result.get("report", {}).get("attempts")
                        and all(item.get(key) == value for item in result["report"]["attempts"])
                    ),
                    f"Authorized {key} filter selects only matching unique attempts",
                )
                for name, (key, value) in keys.items()
                for result in (selected[name],)
            }
        elif scenario == "t62_d":
            exported = _read(client, export="csv")
            exported_json = _read(client, export="json")
            csv_rows = exported.get("rows", [])
            reconciled, financial_detail = (
                _csv_finance_reconcile(
                    csv_rows,
                    exported_json.get("report", {}).get("attempts", []),
                    exported_json.get("report", {}).get("total", {}),
                )
                if (exported["status"] == exported_json["status"] == 200)
                else (False, {})
            )
            selected = {
                "csv": csv_rows,
                "json_export": exported_json,
                "full": full_result,
                "financial_reconciliation": financial_detail,
            }
            checks = {
                "t62_d.timeline_csv_json_reconcile": (
                    bool(
                        exported["status"] == exported_json["status"] == 200
                        and reconciled
                        and {item["attempt_id"] for item in rows}
                        == {item["attempt_id"] for item in csv_rows}
                        and exported_json["report"]["total"] == full["total"]
                        and _known_sum(rows) == Decimal(full["total"]["known_usd"])
                    ),
                    "CSV and JSON contain matching per-attempt finance and independently summed USD",
                )
            }
        elif scenario == "t62_e":
            with _operator_client(runtime, "other") as other:
                other_report = _read(other)
                other_csv = _read(other, export="csv")
                other_filtered = _read(other, {"actor_id": rows[0]["actor_id"]})
            selected = {
                "ordinary": other_report,
                "ordinary_csv": other_csv,
                "ordinary_filtered": other_filtered,
                "admin_total": full["total"],
            }
            visible = other_report.get("report", {}).get("attempts", [])
            checks = {
                "t62_e.cross_principal_denial": (
                    bool(
                        other_report["status"]
                        == other_csv["status"]
                        == other_filtered["status"]
                        == 200
                        and all(
                            item["principal_id"] == "user.other.synthetic"
                            or item.get("initiating_user_id") == "user.other.synthetic"
                            for item in visible
                        )
                        and not {item["attempt_id"] for item in rows}.intersection(
                            {item["attempt_id"] for item in visible}
                        )
                        and not other_csv["rows"]
                        and not other_filtered["report"]["attempts"]
                    ),
                    "Ordinary principal receives no other-principal attempt or export row",
                )
            }
        elif scenario in {"t64", "t65"}:
            attestation, attestation_hash = _browser_attestation(
                runtime,
                "operator-browser-evidence.json"
                if scenario == "t64"
                else "preview-browser-evidence.json",
                full,
            )
            browser = attestation["browser"]
            selected = {
                "browser_attestation": attestation,
                "browser_attestation_sha256": attestation_hash,
            }
            if scenario == "t64":
                desktop = browser.get("desktop", {})
                narrow = browser.get("narrow", {})
                keyboard = browser.get("keyboard", {})
                management = browser.get("management", {})
                checks = {
                    "t64.keyboard": (
                        bool(
                            keyboard.get("focused_tag") == "BUTTON"
                            and keyboard.get("activated_detail") is True
                        ),
                        "Keyboard focused a real button and opened selected detail",
                    ),
                    "t64.narrow": (
                        bool(
                            all(
                                type(view.get("inner_width")) is int
                                and type(view.get("scroll_width")) is int
                                and view["scroll_width"] <= view["inner_width"] + 2
                                for view in (desktop, narrow)
                            )
                            and narrow.get("inner_width", 0) < desktop.get("inner_width", 0)
                        ),
                        "Desktop and narrower viewport controls stayed within document width",
                    ),
                    "t64.error_reason": (
                        bool(
                            type(browser.get("error_reason")) is str
                            and len(browser["error_reason"].strip()) > 5
                        ),
                        "Browser exposed a concrete management or report error reason",
                    ),
                    "t64.management_edit_or_disabled": (
                        bool(
                            management.get("worked") is True
                            or (
                                management.get("disabled") is True
                                and type(management.get("reason")) is str
                                and management["reason"].strip()
                            )
                        ),
                        "Management edit worked or was disabled with a visible reason",
                    ),
                    "t64.no_secret": (
                        browser.get("secret_text_visible") is False,
                        "Captured browser text contained no synthetic credential or secret",
                    ),
                }
            else:
                seek = browser.get("seek", {})
                checks = {
                    "t65.preview_seek": (
                        bool(
                            seek.get("start") == 0
                            and type(seek.get("midpoint")) in (int, float)
                            and type(seek.get("end")) in (int, float)
                            and 0 < seek["midpoint"] < seek["end"]
                        ),
                        "Isolated preview exposed start, midpoint and end seek positions",
                    ),
                    "t65.replay_no_send": (
                        bool(
                            browser.get("replayed") is True
                            and attestation["ledger_before"] == attestation["ledger_after"]
                        ),
                        "Replaying did not change retained attempt or receiver census",
                    ),
                    "t65.no_ledger_mutation": (
                        bool(
                            attestation["ledger_before"] == attestation["ledger_after"]
                            and _same_census(before, _census(runtime))
                        ),
                        "Read-only preview did not modify operational or target ledger",
                    ),
                }
        else:
            raise NotImplementedError(scenario)
    after = _census(runtime)
    if not _same_census(before, after):
        raise AssertionError("operator reads or browser attestation changed target attempts/sends")
    stages = {
        "operator": {
            "http_status": full_result["status"],
            "attempts": len(rows),
            "before": before,
            "after": after,
        }
    }
    if scenario == "t62_b":
        stages["settlement"] = {
            "accepted_revision": 3,
            "attempt_id": correction["attempt_id"],
            "same_amount": True,
            "new_possible_sends": 0,
        }
    return _retained(runtime, case, stages, checks, selected)


def persistence_migration(runtime, case):
    """Additive readback of a representative old row, independent of live DB."""
    if (case["scenario_id"], case["variant"]) != ("t66", "composed"):
        raise NotImplementedError("unsupported preserving migration case")
    from ezllmrouter_server.store import SQLiteStore

    before = _census(runtime)
    path = runtime.root / "cases" / (case["id"] + "-legacy.sqlite")
    path.parent.mkdir(exist_ok=True)
    if path.exists():
        raise RuntimeError("one-use migration fixture already exists")
    key = {
        "principal_id": "user.legacy.synthetic",
        "task_id": "task.legacy.synthetic",
        "step_id": "step.legacy.synthetic",
    }
    encoded_key = json.dumps(key, sort_keys=True, separators=(",", ":"))
    old_record = json.dumps(
        {
            "submission_id": "submission.legacy.synthetic",
            "attempt_id": "attempt.legacy.synthetic",
            "price_version": "price.legacy.synthetic",
            "exposure_state": "unknown",
            "settlement_state": "unknown",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    old_usage = json.dumps(
        {"attempt_id": "attempt.legacy.synthetic", "revision": 2, "cost_status": "unknown"},
        sort_keys=True,
        separators=(",", ":"),
    )
    old_usage_first = json.dumps(
        {"attempt_id": "attempt.legacy.synthetic", "revision": 1, "cost_status": "unknown"},
        sort_keys=True,
        separators=(",", ":"),
    )
    old_grant = json.dumps(
        {"principal_id": "user.legacy.synthetic", "revision": 7, "status": "active"},
        sort_keys=True,
        separators=(",", ":"),
    )
    db = sqlite3.connect(path)
    try:
        db.executescript(
            "CREATE TABLE submissions (submission_id TEXT PRIMARY KEY, principal_id TEXT NOT NULL, "
            "task_id TEXT NOT NULL, work_key TEXT NOT NULL, work_digest TEXT NOT NULL, record TEXT NOT NULL, "
            "UNIQUE(principal_id, work_key));"
            "CREATE TABLE usage_revisions (attempt_id TEXT NOT NULL, revision INTEGER NOT NULL, "
            "submission_id TEXT NOT NULL, usage TEXT NOT NULL, PRIMARY KEY(attempt_id,revision));"
            "CREATE TABLE registry_grants (principal_id TEXT NOT NULL, config_ref TEXT NOT NULL, "
            "record TEXT NOT NULL, PRIMARY KEY(principal_id,config_ref));"
        )
        db.execute(
            "INSERT INTO submissions VALUES (?,?,?,?,?,?)",
            (
                "submission.legacy.synthetic",
                key["principal_id"],
                key["task_id"],
                encoded_key,
                "sha256:legacy.synthetic",
                old_record,
            ),
        )
        db.executemany(
            "INSERT INTO usage_revisions VALUES (?,?,?,?)",
            [
                ("attempt.legacy.synthetic", 1, "submission.legacy.synthetic", old_usage_first),
                ("attempt.legacy.synthetic", 2, "submission.legacy.synthetic", old_usage),
            ],
        )
        db.execute(
            "INSERT INTO registry_grants VALUES (?,?,?)",
            ("user.legacy.synthetic", "configuration.legacy.synthetic", old_grant),
        )
        db.commit()
    finally:
        db.close()
    store = SQLiteStore(path)
    try:
        record = store.db.execute("SELECT record FROM submissions").fetchone()[0]
        usage = [
            row[0]
            for row in store.db.execute("SELECT usage FROM usage_revisions ORDER BY revision")
        ]
        grant = store.db.execute("SELECT record FROM registry_grants").fetchone()[0]
        owner = store.work_owner(key)
        initial = {"record": record, "usage": usage, "grant": grant, "owner": owner}
    finally:
        store.close()
    reopened = SQLiteStore(path)
    try:
        again = {
            "record": reopened.db.execute("SELECT record FROM submissions").fetchone()[0],
            "usage": [
                row[0]
                for row in reopened.db.execute(
                    "SELECT usage FROM usage_revisions ORDER BY revision"
                )
            ],
            "grant": reopened.db.execute("SELECT record FROM registry_grants").fetchone()[0],
            "owner": reopened.work_owner(key),
        }
    finally:
        reopened.close()
    after = _census(runtime)
    checks = {
        "t66.old_row_migration": (
            initial["record"] == old_record
            and owner
            == {"contract_version": "0.2", "submission_id": "submission.legacy.synthetic"},
            "Additive migration indexed old WorkKey without changing old record bytes",
        ),
        "t66.backup_readback": (
            initial == again and before == after and usage == [old_usage_first, old_usage],
            "Reopen readback preserved both usage revisions, grant and live campaign counters",
        ),
        "t66.unknown_exposure": (
            json.loads(again["record"])["exposure_state"] == "unknown"
            and all(json.loads(row)["cost_status"] == "unknown" for row in again["usage"]),
            "Unknown legacy exposure and usage remain unknown after migration",
        ),
        "t66.one_use_runs": (
            again["owner"] == initial["owner"]
            and after["possible_send_count"] == before["possible_send_count"],
            "Repeated migration open did not create or replay a send",
        ),
    }
    return _retained(
        runtime,
        case,
        {
            "persistence": {
                "fixture_path": str(path),
                "fixture_sha256": sha256(path.read_bytes()).hexdigest(),
                "live_before": before,
                "live_after": after,
            }
        },
        checks,
        {
            "seed": {
                "work_key": key,
                "record": old_record,
                "usage": [old_usage_first, old_usage],
                "grant": old_grant,
            },
            "first_readback": initial,
            "second_readback": again,
        },
    )


def _registration(name, run, supported):
    return CaseHandler(
        name=name,
        source_path=str(SOURCE),
        source_sha256=sha256(SOURCE.read_bytes()).hexdigest(),
        supported=frozenset(supported),
        run=run,
    )


OPERATOR_CASE_HANDLERS = {
    "operator_identity": _registration(
        "operator_identity", operator_identity, {("t60", "composed")}
    ),
    "operator_reporting": _registration(
        "operator_reporting",
        operator_reporting,
        {
            (scenario, "composed")
            for scenario in ("t61", "t62_a", "t62_b", "t62_c", "t62_d", "t62_e", "t64", "t65")
        },
    ),
    "persistence_migration": _registration(
        "persistence_migration", persistence_migration, {("t66", "composed")}
    ),
}
