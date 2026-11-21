"""dev12_completion_handlers handler common domain; entry points remain on the facade."""

from __future__ import annotations


def _current_utc():
    from tools.gateway.evidence import dev12_completion_handlers as _api

    return _api.datetime.now(_api.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _case_request(runtime, case, vector="DIRECT_DOCUMENT", *, item_id="doc.valid"):
    from tools.gateway.evidence.dev12_integrated import fixture

    request, _ = fixture(vector)
    request["work_selector"]["step_id"] = (
        "step.completion02."
        + case["scenario_id"].replace("_", ".")
        + "."
        + case["variant"].replace("_", ".")
    )[:150]
    if case["scenario_id"].startswith("ct02_") and ".continuation" in case["id"]:
        # A failed supplemental case with retained evidence gets a distinct
        # declared WorkKey; never replay its earlier possibly sent attempt.
        request["work_selector"]["step_id"] += "." + case["id"].rsplit(".continuation", 1)[1]
    if request["operation"]["type"] == "embedding.create":
        request["input"]["items"] = [{"item_id": item_id, "text": "Sky"}]
    return request


def _headers(runtime, vector="DIRECT_DOCUMENT", *, version="0.3"):
    return {
        "Authorization": "Bearer " + runtime.credentials[vector],
        "EzLLMRouter-Contract-Version": version,
        "Content-Type": "application/json",
        "EzLLMRouter-Wait-Ms": "5000",
    }


def _census(runtime):
    from tools.gateway.evidence.dev12_integrated import observations

    with runtime.store._lock:
        submissions = runtime.store.db.execute("SELECT COUNT(*) FROM dev12_submissions").fetchone()[
            0
        ]
        guard = runtime.store.db.execute("SELECT COUNT(*) FROM dev12_send_ownership").fetchone()[0]
        usage = runtime.store.db.execute("SELECT COUNT(*) FROM dev12_usage_revisions").fetchone()[0]
    arrivals = len(observations(runtime.receiver_log))
    return {
        "submissions": submissions,
        "guard_ownership": guard,
        "usage_revisions": usage,
        "receiver_arrivals": arrivals,
        "campaign": runtime.allowance.inspect(),
    }


def _post(runtime, request, headers):
    from tools.gateway.evidence import dev12_completion_handlers as _api
    import httpx

    with httpx.Client(base_url=runtime.base_url, timeout=12, trust_env=False) as client:
        reply = client.post("/v1/submissions", headers=headers, json=request)
        value = reply.json()
        status = None
        sid = value.get("handle", {}).get("submission_id")
        if sid:
            for _ in range(100):
                current = client.get(
                    "/v1/submissions/" + sid,
                    headers={
                        "Authorization": headers["Authorization"],
                        "EzLLMRouter-Contract-Version": headers["EzLLMRouter-Contract-Version"],
                    },
                )
                status = current.json()
                if status.get("submission_state") != "pending":
                    break
                _api.time.sleep(0.05)
        return {"http_status": reply.status_code, "reply": value, "status": status}


def _trusted(runtime, vector="DIRECT_DOCUMENT"):
    from tools.gateway.evidence.dev12_integrated import fixture

    context = runtime.contexts_by_credential[runtime.credentials[vector]]
    return {
        **context["identity"],
        "task_id": fixture(vector)[0]["work_selector"]["task_id"],
        "expires_at": context["expires_at"],
    }


def _unknown_then_retained_correction(runtime, case, item_id, suffix):
    """One genuine unknown native observation, then an independent receipt."""
    from tools.gateway.evidence import dev12_completion_handlers as _api

    request = _api._case_request(runtime, case, item_id=item_id)
    request["work_selector"]["step_id"] += "." + suffix
    before = _api._census(runtime)
    reply = _api._post(runtime, request, _api._headers(runtime))
    paused = _api._census(runtime)
    status = reply["status"] or {}
    sid = reply["reply"].get("handle", {}).get("submission_id")
    usage = status.get("attempts", [{}])[0].get("usage_revision", {})
    if (
        not sid
        or status.get("submission_state") != "completed"
        or usage.get("cost_status") != "unknown"
        or not paused["campaign"]["paused"]
        or paused["receiver_arrivals"] != before["receiver_arrivals"] + 1
    ):
        raise AssertionError("native unknown observation/delivery/receiver correlation missing")
    outcome = runtime.successor.collect_receiver_receipt(sid, _api._trusted(runtime))
    corrected = runtime.successor.status(sid, _api._trusted(runtime))
    decision = runtime.successor.resume_campaign(
        sid, _api._trusted(runtime), "test retained native receipt correction"
    )
    after = _api._census(runtime)
    if (
        outcome != "accepted"
        or decision.get("decision") != "resumed"
        or corrected["attempts"][0]["usage_revision"].get("cost_status") != "calculated"
        or after["receiver_arrivals"] != paused["receiver_arrivals"]
        or after["campaign"]["possible_send_count"] != paused["campaign"]["possible_send_count"]
    ):
        raise AssertionError("historical correction or same-scope resume was not no-send")
    return {
        "request": request,
        "reply": reply,
        "status_before": status,
        "before": before,
        "paused": paused,
        "collection": outcome,
        "status_after": corrected,
        "resume": decision,
        "after": after,
    }


def _evidence(runtime, case, stages, checks, payload, attempt_group):
    """Retain one bounded case document and bind every assertion to its hash."""
    from tools.gateway.evidence import dev12_completion_handlers as _api

    expected = set(case["predicates"])
    if set(checks) != expected:
        raise AssertionError("handler did not execute exact registered assertions")
    if not all(
        type(value) is tuple
        and len(value) == 2
        and type(value[0]) is bool
        and type(value[1]) is str
        and value[1]
        for value in checks.values()
    ):
        raise AssertionError("objective assertion result malformed")
    directory = runtime.root / "cases"
    directory.mkdir(exist_ok=True)
    path = directory / (case["id"] + ".json")
    if path.exists() or path.is_symlink():
        raise RuntimeError("case evidence already exists; do not overwrite a run")
    document = {
        "case_id": case["id"],
        "scenario_id": case["scenario_id"],
        "variant": case["variant"],
        "at": _api._current_utc(),
        "attempt_group": case["attempt_group"],
        "actual_attempt_id": attempt_group,
        "observed_stages": stages,
        "checks": {
            name: {"passed": result[0], "detail": result[1]} for name, result in checks.items()
        },
        "payload": payload,
    }
    raw = (_api.json.dumps(document, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()
    if len(raw) > 1_000_000:
        raise AssertionError("case evidence exceeds bound")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        import os

        os.fsync(stream.fileno())
    domain_digest = _api.sha256(raw).hexdigest()
    relative = str(path.relative_to(runtime.root))
    stage_rows = [
        {
            "stage": name,
            "evidence_path": relative,
            "sha256": domain_digest,
            "case_id": case["id"],
            "attempt_group": case["attempt_group"],
            "observed": observed,
        }
        for name, observed in stages.items()
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
        "status": "PASS" if all(row["passed"] for row in assertions) else "FAIL",
        "observations": stage_rows,
        "assertions": assertions,
    }
