"""Bounded missing-case handlers for the retained Completion 02 campaign.

Import is inert. All work is performed only after the separate no-send
supplement preflight and release gate have checked the durable allowance.
"""

from __future__ import annotations

from tools.gateway.paths import source_root

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import os
import subprocess
import threading
from unittest.mock import patch

from tools.gateway.evidence.dev12_completion_handlers import (
    _case_request,
    _census,
    _evidence,
    _headers,
    _post,
)


def _legacy_prewrite_setup(runtime):
    """Enable only the frozen local 0.2 admission path for ownership controls.

    The adapter deliberately returns a definite error before guard commit or
    bytes. The 0.3 cases still use the real isolated worker/receiver. This
    route cannot contact a provider and is counted as one legacy admission.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from ezllmrouter_server.canonical import ContractError
    from ezllmrouter_server.plans import PlanAuthority
    from ezllmrouter_server.gateway.synthetic_recipe import SyntheticDevelopmentRecipe

    fixture = json.loads(
        (source_root(__file__) / "tests/development_slice/fixture.json").read_text()
    )

    class DefinitePrewrite:
        def prepare(self, body):
            return json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()

        def describe(self, raw, timeout_ms, destination):
            return {
                "method": "POST",
                "url": "http://receiver:8766/v1/chat/completions",
                "content_type": "application/json",
                "content_length": len(raw),
                "body_sha256": sha256(raw).hexdigest(),
                "timeout_ms": timeout_ms,
                "processing_region": destination["processing_region"],
            }

        def send_with_context(self, raw, timeout_ms, expected, context):
            if self.describe(raw, timeout_ms, context["plan"]["destination"]) != expected:
                raise AssertionError("legacy local recipe changed")
            context["fresh_check"]()
            raise ContractError("INTENT_PERSIST_FAILED", 503)

    core = runtime.coordinator
    # Wire 0.2 has additional prompt/context identity fields. They are local
    # fixture claims on this disposable credential, never account grants.
    core.identity[runtime.credentials["DIRECT_DOCUMENT"]].update(
        {
            "context_id": "ctx.dev12.synthetic.legacy",
            "issuer_id": "issuer.synthetic",
            "prompt_id": fixture["trusted_context"]["prompt_id"],
            "prompt_version": fixture["trusted_context"]["prompt_version"],
        }
    )
    core.config = deepcopy(fixture["destination"])
    core.prompt_blocks = deepcopy(fixture["prompt_blocks"])
    core.allowed_lineages = deepcopy(fixture["allowed_lineages"])
    core.authority = PlanAuthority(Ed25519PrivateKey.generate(), deepcopy(fixture["policy"]))
    core.adapter = DefinitePrewrite()
    core.retention = deepcopy(fixture["retention"])
    core.classification = deepcopy(fixture["classification"])
    core.recipe = SyntheticDevelopmentRecipe()
    core.trusted_source_labels = deepcopy(fixture["trusted_source_labels"])


def _workkey(runtime, case):
    """Both cross-version owner orders and normal synchronized HTTP contention."""
    from concurrent.futures import ThreadPoolExecutor

    variant = case["variant"]
    successor = _case_request(runtime, case)
    legacy = json.loads(
        (source_root(__file__) / "tests/development_slice/request.json").read_text()
    )
    legacy["step_id"] = successor["work_selector"]["step_id"]
    legacy["task_id"] = successor["work_selector"]["task_id"]
    legacy["step_revision"] = successor["work_selector"]["step_revision"]
    legacy["execution_generation"] = successor["work_selector"]["execution_generation"]
    legacy["requested_configuration_ref"] = "cfg.demo"
    with runtime.store._lock:
        before_legacy = runtime.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
    before = _census(runtime)
    if variant == "wire02_first":
        _legacy_prewrite_setup(runtime)
        first = _post(runtime, legacy, _headers(runtime, version="0.2"))
        middle = _census(runtime)
        conflict = _post(runtime, successor, _headers(runtime))
        expected_wire = "0.3"
    elif variant == "wire03_first":
        first = _post(runtime, successor, _headers(runtime))
        middle = _census(runtime)
        _legacy_prewrite_setup(runtime)
        conflict = _post(runtime, legacy, _headers(runtime, version="0.2"))
        expected_wire = "0.2"
    else:
        contender = deepcopy(successor)
        contender["input"]["items"][0]["text"] = "River"
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(_post, runtime, request, _headers(runtime))
                for request in (successor, contender)
            ]
            replies = [future.result(timeout=30) for future in futures]
        first = next((item for item in replies if item["reply"].get("handle")), {})
        conflict = next((item for item in replies if item["http_status"] == 409), {})
        middle = None
        expected_wire = "0.3"
    after = _census(runtime)
    with runtime.store._lock:
        after_legacy = runtime.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
        key = {
            "principal_id": runtime.contexts_by_credential[runtime.credentials["DIRECT_DOCUMENT"]][
                "identity"
            ]["principal_id"],
            **successor["work_selector"],
        }
        owner = runtime.store.work_owner(key)
    conflict_code = "WORK_VERSION_CONFLICT" if variant == "wire02_first" else "WORK_CONFLICT"
    projected_error = (
        conflict.get("reply", {})
        if expected_wire == "0.3"
        else conflict.get("reply", {}).get("error", {})
    )
    conflict_ok = (
        conflict.get("http_status") == 409
        and projected_error.get("code") == conflict_code
        and projected_error.get("retry_guidance") == "never"
    )
    if variant == "wire02_first":
        owned = (
            after_legacy == before_legacy + 1
            and after["submissions"] == before["submissions"]
            and owner
            and owner["contract_version"] == "0.2"
            and first["http_status"] == 503
            and first["reply"].get("error", {}).get("code") == "INTENT_PERSIST_FAILED"
            and after["receiver_arrivals"] == before["receiver_arrivals"]
            and after["guard_ownership"] == before["guard_ownership"]
        )
    elif variant == "wire03_first":
        owned = (
            after_legacy == before_legacy
            and after["submissions"] == before["submissions"] + 1
            and owner
            and owner["contract_version"] == "0.3"
            and first["status"] is not None
            and first["status"].get("submission_state") == "completed"
            and middle["guard_ownership"] == before["guard_ownership"] + 1
            and middle["receiver_arrivals"] == before["receiver_arrivals"] + 1
            and after["guard_ownership"] == middle["guard_ownership"]
            and after["receiver_arrivals"] == middle["receiver_arrivals"]
        )
    else:
        owned = (
            after_legacy == before_legacy
            and after["submissions"] == before["submissions"] + 1
            and first.get("status") is not None
            and first["status"].get("submission_state") == "completed"
            and after["guard_ownership"] == before["guard_ownership"] + 1
            and after["receiver_arrivals"] == before["receiver_arrivals"] + 1
            and owner
            and owner["contract_version"] == "0.3"
        )
    checks = {
        f"ct02_workkey.{variant}": (
            bool(conflict_ok and owned),
            "One durable WorkKey owner with selected-wire 409/never and no competing send",
        )
    }
    stages = {
        "ingress": {
            "first_http": first.get("http_status"),
            "conflict_http": conflict.get("http_status"),
        },
        "admission": {
            "successor_delta": after["submissions"] - before["submissions"],
            "legacy_delta": after_legacy - before_legacy,
        },
        "guard": {
            "successor_ownership_delta": after["guard_ownership"] - before["guard_ownership"]
        },
        "receiver": {
            "successor_arrivals_delta": after["receiver_arrivals"] - before["receiver_arrivals"]
        },
    }
    return _evidence(
        runtime,
        case,
        stages,
        checks,
        {
            "first": first,
            "conflict": conflict,
            "owner": owner,
            "before": before,
            "middle": middle,
            "after": after,
            "legacy_before": before_legacy,
            "legacy_after": after_legacy,
            "legacy_counted_worst_case_admission": int(variant == "wire02_first"),
        },
        first.get("reply", {}).get("attempt_id", "none"),
    )


def _recovery(runtime, case):
    """Exact installed SDK status/duplicate recovery under logical retention."""
    from ezllmrouter_client import EzLLMRouterClient, EzLLMRouterError

    variant = case["variant"]
    # A retry of the wheel's status-only recovery must use the original
    # selector even if its evidence document needs a new one-use case ID.
    request_case = {**case, "id": "case.ct02_recovery.wheel"} if variant == "wheel" else case
    request = _case_request(runtime, request_case)
    before = _census(runtime)
    key = {
        "principal_id": runtime.contexts_by_credential[runtime.credentials["DIRECT_DOCUMENT"]][
            "identity"
        ]["principal_id"],
        **request["work_selector"],
    }
    prior = runtime.store.successor_by_work(key)
    if prior is not None:
        # A stopped case may already have performed its one authorized send.
        # Reuse its exact admitted bytes and independent ownership/arrival;
        # never resubmit under a new WorkKey merely to repair test plumbing.
        if variant != "wheel" or prior["campaign_id"] != runtime.allowance.campaign_id:
            raise AssertionError("unexpected retained recovery setup")
        sid = prior["submission_id"]
        request = deepcopy(prior["request"])
        with runtime.store._lock:
            ownership = runtime.store.db.execute(
                "SELECT COUNT(*) FROM dev12_send_ownership WHERE attempt_id=? AND submission_id=?",
                (prior["attempt_id"], sid),
            ).fetchone()[0]
        arrivals = sum(
            row.get("attempt_id") == prior["attempt_id"]
            for row in (json.loads(line) for line in runtime.receiver_log.read_text().splitlines())
        )
        observed = _post_status(runtime, {"submission_id": sid}, _headers(runtime))
        if (
            ownership != 1
            or arrivals != 1
            or observed["http_status"] != 200
            or observed["body"].get("submission_state") != "completed"
        ):
            raise AssertionError("retained recovery setup lacks one owned receiver arrival")
        sent = {
            "http_status": observed["http_status"],
            "reply": {"handle": {"submission_id": sid}, "attempt_id": prior["attempt_id"]},
            "status": observed["body"],
            "retained_prior_setup": True,
            "owned_receiver_arrivals": arrivals,
        }
    else:
        sent = _post(runtime, request, _headers(runtime))
        sid = sent["reply"].get("handle", {}).get("submission_id")
    if not sid or not sent["status"] or sent["status"].get("submission_state") != "completed":
        raise AssertionError("recovery control did not complete once")
    admitted = _census(runtime)
    record = runtime.store.successor_get(sid)
    old_direct_token = runtime.credentials["DIRECT_DOCUMENT"]
    if variant == "wheel":
        retained = runtime.root / "continuation-direct-secret.json"
        if retained.exists():
            # The previous stopped case committed the one-use registry change.
            # _bind_contexts loaded this private token; never provision twice.
            if retained.is_symlink() or retained.stat().st_mode & 0o077:
                raise RuntimeError("retained disposable credential unsafe")
            if (
                runtime.registry.credential_principal(old_direct_token)["principal_id"]
                != record["work_key"]["principal_id"]
            ):
                raise AssertionError("renewed credential does not bind original owner")
            old_direct_token = "dev12.completion02.synthetic.0." + "x" * 32
        else:
            principal = runtime.registry.principal(record["work_key"]["principal_id"])
            _credential, new_token = runtime.registry.provision_credential(
                "owner.local",
                record["work_key"]["principal_id"],
                principal["revision"],
                "op.dev12.ct02.renew.direct",
            )
            if not new_token:
                raise AssertionError("one-use synthetic credential renewal unavailable")
            with os.fdopen(
                os.open(retained, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
            ) as stream:
                stream.write((json.dumps({"direct": new_token}) + "\n").encode())
                stream.flush()
                os.fsync(stream.fileno())
            context = runtime.contexts_by_credential.pop(old_direct_token)
            runtime.contexts_by_credential[new_token] = context
            runtime.coordinator.identity[new_token] = runtime.coordinator.identity.pop(
                old_direct_token
            )
            runtime.credentials["DIRECT_DOCUMENT"] = new_token
    selector_id = {"submission_id": sid}
    selector_work = {"work_selector": deepcopy(request["work_selector"])}
    cutoff = datetime.fromisoformat(
        record["result_available_at"].replace("Z", "+00:00")
    ) + timedelta(days=7)
    before_cutoff = (cutoff - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    at_cutoff = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    # This is a renewed disposable credential, evaluated at a seven-day
    # logical retention clock. Keep its synthetic authenticated context valid
    # for that clock; the original admitted context and real campaign expiry
    # remain immutable. No registry grant or operational identity is changed.
    synthetic_expiry = (cutoff + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    current_token = runtime.credentials["DIRECT_DOCUMENT"]
    runtime.contexts_by_credential[current_token]["expires_at"] = synthetic_expiry
    runtime.coordinator.identity[current_token]["expires_at"] = synthetic_expiry
    original_clock = runtime.successor.clock
    outcomes = {}

    def wheel(duplicate):
        with EzLLMRouterClient(
            runtime.base_url, runtime.credentials["DIRECT_DOCUMENT"], timeout=12
        ) as client:
            selected = {
                "by_id": client.get_successor_status(selector_id),
                "by_work": client.get_successor_status(selector_work),
            }
            if duplicate:
                try:
                    selected["duplicate"] = client.submit_embedding(request, {"wait_ms": 5000})
                except EzLLMRouterError as exc:
                    selected["duplicate_error"] = {
                        "code": exc.code,
                        "http_status": exc.http_status,
                        "retry_guidance": exc.retry_guidance,
                        "handle": exc.handle,
                    }
            return selected

    def tarball(duplicate, label):
        private = runtime.root / "cases" / (case["id"] + "." + label + ".js-private-input.json")
        data = {
            "package_path": str(runtime.installed_js_root),
            "base_url": runtime.base_url,
            "token": runtime.credentials["DIRECT_DOCUMENT"],
            "action": "recover",
            "selectors": {"by_id": selector_id, "by_work": selector_work},
            "duplicate_request": request if duplicate else None,
        }
        raw = (json.dumps(data, sort_keys=True, ensure_ascii=True) + "\n").encode()
        with os.fdopen(
            os.open(private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
        ) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        run = subprocess.run(
            [
                "/dev12-node",
                str(Path(__file__).with_name("dev12_completion_js_actor.cjs")),
                str(private),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if run.returncode:
            raise AssertionError("exact installed CommonJS recovery failed: " + run.stderr[-400:])
        return json.loads(run.stdout)

    selected = wheel if variant == "wheel" else tarball
    try:
        runtime.successor.clock = lambda: before_cutoff
        outcomes["before"] = selected(True) if variant == "wheel" else selected(True, "before")
        outcomes["old_credential_denial"] = (
            _post_status(
                runtime,
                selector_id,
                {
                    "Authorization": "Bearer " + old_direct_token,
                    "EzLLMRouter-Contract-Version": "0.3",
                },
            )
            if variant == "wheel"
            else None
        )
        identity = record["trusted_identity"]
        runtime.authority.set_historical_access(
            identity, read=False, write=True, resume=True, observed_at=before_cutoff
        )
        outcomes["current_denial"] = _post_status(runtime, selector_id, _headers(runtime))
        runtime.authority.set_historical_access(
            identity, read=True, write=True, resume=True, observed_at=before_cutoff
        )
        outcomes["renewed"] = _post_status(runtime, selector_work, _headers(runtime))
        runtime.successor.clock = lambda: at_cutoff
        outcomes["cutoff"] = selected(True) if variant == "wheel" else selected(True, "cutoff")
        changed = deepcopy(request)
        changed["input"]["items"][0]["text"] = "River"
        outcomes["changed"] = _post(runtime, changed, _headers(runtime))
        legacy = json.loads(
            (source_root(__file__) / "tests/development_slice/request.json").read_text()
        )
        legacy["task_id"] = request["work_selector"]["task_id"]
        legacy["step_id"] = request["work_selector"]["step_id"]
        legacy["step_revision"] = request["work_selector"]["step_revision"]
        legacy["execution_generation"] = request["work_selector"]["execution_generation"]
        legacy["requested_configuration_ref"] = "cfg.demo"
        legacy["deadline"] = at_cutoff
        _legacy_prewrite_setup(runtime)
        outcomes["wrong_version"] = _post(runtime, legacy, _headers(runtime, version="0.2"))
    finally:
        runtime.successor.clock = original_clock
        if not runtime.authority.historical_allowed(record["trusted_identity"], record, "read"):
            runtime.authority.set_historical_access(
                record["trusted_identity"],
                read=True,
                write=True,
                resume=True,
                observed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
    after = _census(runtime)

    def status(item, key):
        return item[key] if variant == "wheel" else item[key].get("status")

    def duplicate(item):
        return item.get("duplicate") if variant == "wheel" else item["duplicate"]

    before_result = outcomes["before"]
    cutoff_result = outcomes["cutoff"]
    initial_visible = all(
        status(before_result, key) and status(before_result, key)["candidate_access"] == "present"
        for key in ("by_id", "by_work")
    )
    expired_visible = all(
        status(cutoff_result, key)
        and status(cutoff_result, key)["candidate_access"] == "expired"
        and "result" not in status(cutoff_result, key)["attempts"][0]
        and status(cutoff_result, key)["attempts"][0]["settlement_state"]
        == sent["status"]["attempts"][0]["settlement_state"]
        for key in ("by_id", "by_work")
    )
    before_duplicate = duplicate(before_result) or {}
    cutoff_duplicate = duplicate(cutoff_result) or {}
    duplicate_before_ok = (
        before_duplicate.get("handle", {}).get("submission_id") == sid
        if variant == "wheel"
        else before_duplicate.get("reply", {}).get("handle", {}).get("submission_id") == sid
    )
    cutoff_error = (
        outcomes["cutoff"].get("duplicate_error")
        if variant == "wheel"
        else cutoff_duplicate.get("error")
    ) or {}
    checks = {
        f"ct02_recovery.{variant}.selectors": (
            bool(initial_visible and expired_visible),
            "Both installed-client selectors retain same attempt and finance before/at cutoff",
        ),
        f"ct02_recovery.{variant}.duplicate": (
            bool(
                duplicate_before_ok
                and cutoff_error.get("code") == "POLICY_DENIED"
                and cutoff_error.get("http_status") == 403
                and cutoff_error.get("retry_guidance") == "query_first"
            ),
            "Unchanged duplicate recovers before cutoff and becomes strict query-first at cutoff",
        ),
        f"ct02_recovery.{variant}.denial": (
            bool(
                outcomes["current_denial"]["http_status"] == 404
                and (variant != "wheel" or outcomes["old_credential_denial"]["http_status"] == 401)
                and outcomes["renewed"]["http_status"] == 200
                and outcomes["changed"]["http_status"] == 409
                and outcomes["wrong_version"]["http_status"] == 409
            ),
            "Current denial is non-enumerating; restored auth reads; conflicts remain conflicts",
        ),
        f"ct02_recovery.{variant}.no_repeat": (
            bool(
                after["submissions"] == admitted["submissions"]
                and after["guard_ownership"] == admitted["guard_ownership"]
                and after["receiver_arrivals"] == admitted["receiver_arrivals"]
                and after["campaign"]["cumulative_reserved_decimal"]
                == admitted["campaign"]["cumulative_reserved_decimal"]
            ),
            "Read, duplicate and denied recovery allocated no additional attempt or send",
        ),
    }
    return _evidence(
        runtime,
        case,
        {
            "client": {"artifact": variant, "selectors": ["submission_id", "work_selector"]},
            "admission": {"new": admitted["submissions"] - before["submissions"]},
            "settlement": {
                "before": sent["status"]["attempts"][0]["settlement_state"],
                "after": status(cutoff_result, "by_id")["attempts"][0]["settlement_state"],
            },
        },
        checks,
        {
            "request": request,
            "sent": sent,
            "outcomes": outcomes,
            "before": before,
            "admitted": admitted,
            "after": after,
            "cutoff_origin": record["result_available_at"],
            "cutoff": at_cutoff,
            "renewed_synthetic_context_expires_at": synthetic_expiry,
        },
        record["attempt_id"],
    )


def _post_status(runtime, selector, headers):
    import httpx

    if "submission_id" in selector:
        path = "/v1/submissions/" + selector["submission_id"]
    else:
        value = selector["work_selector"]
        path = "/v1/submissions/by-work/" + "/".join(
            str(value[key])
            for key in ("task_id", "step_id", "step_revision", "execution_generation")
        )
    with httpx.Client(base_url=runtime.base_url, timeout=12, trust_env=False) as client:
        response = client.get(path, headers=headers)
    return {"http_status": response.status_code, "body": response.json()}


def _authenticated(runtime, vector="DIRECT_DOCUMENT"):
    """Reacquire current identity through the Coordinator for each operation."""
    return runtime.coordinator.authenticate(runtime.credentials[vector])


def _failed_unknown(runtime, case):
    request = _case_request(runtime, case, item_id="doc.failure.invalid")
    before = _census(runtime)
    sent = _post(runtime, request, _headers(runtime))
    paused = _census(runtime)
    sid = sent["reply"].get("handle", {}).get("submission_id")
    status = sent["status"] or {}
    if (
        not sid
        or status.get("submission_state") != "failed"
        or status["attempts"][0]["usage_revision"]["cost_status"] != "unknown"
        or not paused["campaign"]["paused"]
        or paused["receiver_arrivals"] != before["receiver_arrivals"] + 1
    ):
        raise AssertionError("failed-delivery unknown native control unavailable")
    record = runtime.store.successor_get(sid)
    identity = record["trusted_identity"]
    runtime.authority.set_historical_access(
        identity,
        read=True,
        write=False,
        resume=False,
        observed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    denied_state = _census(runtime)
    try:
        try:
            runtime.successor.collect_receiver_receipt(sid, _authenticated(runtime))
        except PermissionError:
            denied_write = True
        else:
            denied_write = False
    finally:
        runtime.authority.set_historical_access(
            identity,
            read=True,
            write=True,
            resume=False,
            observed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    after_denial = _census(runtime)
    collected = runtime.successor.collect_receiver_receipt(sid, _authenticated(runtime))
    corrected = runtime.successor.status(sid, _authenticated(runtime))
    after_correction = _census(runtime)
    try:
        runtime.successor.resume_campaign(
            sid, _authenticated(runtime), "synthetic failed-delivery settlement review"
        )
    except PermissionError:
        denied_resume = True
    else:
        denied_resume = False
    runtime.authority.set_historical_access(
        identity,
        read=True,
        write=True,
        resume=True,
        observed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    resumed = runtime.successor.resume_campaign(
        sid, _authenticated(runtime), "synthetic failed-delivery receipt reconciled"
    )
    after = _census(runtime)
    revised = corrected["attempts"][0]["usage_revision"]
    checks = {
        "ct02_failed_unknown.failure_and_unknown": (
            bool(
                status["submission_state"] == corrected["submission_state"] == "failed"
                and status["attempts"][0]["delivery_state"]
                == corrected["attempts"][0]["delivery_state"]
                == "invalid"
                and status["attempts"][0]["usage_revision"]["cost_status"] == "unknown"
                and paused["campaign"]["paused"]
            ),
            "Failed delivery retained independent unknown native cost and affected pause",
        ),
        "ct02_failed_unknown.denied_write": (
            bool(denied_write and after_denial == denied_state),
            "Freshly authenticated write denial changed no history, counter or exposure",
        ),
        "ct02_failed_unknown.late_finance": (
            bool(
                collected == "accepted"
                and revised["revision"] == 2
                and revised["previous_revision"] == 1
                and revised["cost_status"] == "calculated"
                and corrected["submission_state"] == "failed"
                and after_correction["receiver_arrivals"] == paused["receiver_arrivals"]
                and after_correction["campaign"]["possible_send_count"]
                == paused["campaign"]["possible_send_count"]
            ),
            "Genuine same-attempt receiver receipt corrected finance once without delivery rewrite or resend",
        ),
        "ct02_failed_unknown.audited_resume": (
            bool(
                denied_resume
                and resumed.get("decision") == "resumed"
                and after["campaign"]["paused"] is False
                and after["campaign"]["cumulative_reserved_decimal"]
                == paused["campaign"]["cumulative_reserved_decimal"]
            ),
            "Denied then eligible authenticated resume preserved original finite reservation",
        ),
    }
    return _evidence(
        runtime,
        case,
        {
            "receiver": {"arrivals": paused["receiver_arrivals"] - before["receiver_arrivals"]},
            "delivery": {"state": corrected["submission_state"]},
            "settlement": {"before": "unknown", "after": revised["cost_status"]},
            "authority": {"denied_write": denied_write, "denied_resume": denied_resume},
        },
        checks,
        {
            "request": request,
            "sent": sent,
            "record": record,
            "denied_state": denied_state,
            "after_denial": after_denial,
            "collected": collected,
            "corrected": corrected,
            "resume": resumed,
            "before": before,
            "paused": paused,
            "after_correction": after_correction,
            "after": after,
        },
        record["attempt_id"],
    )


def _revision33(runtime, case):
    from ezllmrouter_server.successor_reporting import usage_report

    with runtime.store._lock:
        rows = runtime.store.db.execute(
            "SELECT submission_id,record FROM dev12_submissions WHERE "
            "json_extract(record,'$.work_key.step_id')=?",
            ("step.completion02.t49.e.composed.late",),
        ).fetchall()
        if len(rows) != 1:
            raise AssertionError("retained same-attempt revision source absent")
    sid, record_raw = rows[0]
    record = json.loads(record_raw)
    aid = record["attempt_id"]
    before = _census(runtime)
    before_report = usage_report(
        runtime.store, {"role": "registry_admin", "principal_id": "owner.local"}
    )
    current = runtime.store.successor_latest_usage(aid)
    if current["revision"] != 3 or current["cost_status"] != "calculated":
        raise AssertionError("retained revision-three source changed")
    accepted = []
    for number in range(4, 34):
        row = deepcopy(current)
        row["revision"] = number
        row["previous_revision"] = number - 1
        outcome = runtime.successor.ingest_usage_revision(sid, row, _authenticated(runtime))
        if outcome != "accepted":
            raise AssertionError(f"historical re-adjudication {number} rejected")
        accepted.append(number)
        current = row
    duplicate = runtime.successor.ingest_usage_revision(
        sid, deepcopy(current), _authenticated(runtime)
    )
    negatives = {}
    for label, changed in (
        (
            "conflict",
            {
                **current,
                "components": [
                    {**current["components"][0], "source_ref": "receiver.synthetic.conflict"}
                ],
            },
        ),
        ("skipped", {**current, "revision": 35, "previous_revision": 33}),
        ("self", {**current, "revision": 34, "previous_revision": 34}),
        ("fabricated_history", {**current, "revision": 100, "previous_revision": 99}),
        (
            "changed_price",
            {
                **current,
                "revision": 34,
                "previous_revision": 33,
                "price_ref": "tariff.synthetic.other",
            },
        ),
    ):
        try:
            runtime.successor.ingest_usage_revision(sid, changed, _authenticated(runtime))
        except (ValueError, PermissionError):
            negatives[label] = "rejected"
        else:
            negatives[label] = "accepted"
    with runtime.store._lock:
        foreign_rows = runtime.store.db.execute(
            "SELECT attempt_id,usage FROM dev12_usage_revisions WHERE attempt_id!=? "
            "ORDER BY rowid LIMIT 1",
            (aid,),
        ).fetchall()
    if len(foreign_rows) != 1:
        raise AssertionError("distinct attempt control absent")
    foreign = json.loads(foreign_rows[0][1])
    try:
        runtime.successor.ingest_usage_revision(sid, foreign, _authenticated(runtime))
    except (ValueError, PermissionError):
        negatives["foreign_attempt"] = "rejected"
    else:
        negatives["foreign_attempt"] = "accepted"
    after = _census(runtime)
    after_report = usage_report(
        runtime.store, {"role": "registry_admin", "principal_id": "owner.local"}
    )
    status = runtime.successor.status(sid, _authenticated(runtime))
    latest = runtime.store.successor_latest_usage(aid)
    checks = {
        "ct02_revision33.accepted": (
            bool(
                accepted == list(range(4, 34))
                and latest["revision"] == 33
                and latest["previous_revision"] == 32
                and status["attempts"][0]["usage_revision"] == latest
            ),
            "Persistent accepted same-attempt history reached revision 33 with actual predecessor",
        ),
        "ct02_revision33.duplicate": (
            duplicate in {"duplicate", "existing"}
            and after["usage_revisions"] == before["usage_revisions"] + 30,
            "Identical ordinal duplicate made no extra accepted contribution",
        ),
        "ct02_revision33.negatives": (
            all(value == "rejected" for value in negatives.values()),
            "Conflicting, skipped, self, changed-reference and foreign rows were rejected",
        ),
        "ct02_revision33.latest_once": (
            bool(
                Decimal(after_report["total"]["known_usd"])
                == Decimal(before_report["total"]["known_usd"])
                and after_report["total"]["attempts"] == before_report["total"]["attempts"]
                and after["campaign"]["possible_send_count"]
                == before["campaign"]["possible_send_count"]
                and after["receiver_arrivals"] == before["receiver_arrivals"]
            ),
            "Thirty accepted re-adjudications changed no unique-attempt spend or send",
        ),
    }
    return _evidence(
        runtime,
        case,
        {
            "settlement": {
                "revision_before": 3,
                "revision_after": latest["revision"],
                "accepted_rows": len(accepted),
            },
            "accounting": {
                "known_before": before_report["total"]["known_usd"],
                "known_after": after_report["total"]["known_usd"],
            },
        },
        checks,
        {
            "source_submission_id": sid,
            "source_attempt_id": aid,
            "original_revision": 3,
            "accepted_ordinals": accepted,
            "duplicate": duplicate,
            "negatives": negatives,
            "before": before,
            "after": after,
            "latest": latest,
            "status": status,
            "before_total": before_report["total"],
            "after_total": after_report["total"],
        },
        aid,
    )


def _historical_auth(runtime, case):
    """Fresh authentication, gate-wait revocation and post-expiry settlement."""
    with runtime.store._lock:
        rows = runtime.store.db.execute(
            "SELECT submission_id,record FROM dev12_submissions WHERE "
            "json_extract(record,'$.signed_plan.key_version')='v1' AND "
            "json_extract(record,'$.work_key.principal_id')='user.demo' AND "
            "json_extract(record,'$.submission_state')='completed' ORDER BY rowid"
        ).fetchall()
    selected = next(
        (
            (sid, json.loads(raw))
            for sid, raw in rows
            if runtime.store.successor_latest_usage(json.loads(raw)["attempt_id"])
            and runtime.store.successor_latest_usage(json.loads(raw)["attempt_id"])["cost_status"]
            == "calculated"
        ),
        None,
    )
    if selected is None:
        raise AssertionError("retained revoked-key known-cost source absent")
    sid, record = selected
    identity = record["trusted_identity"]
    key = next(
        item
        for item in runtime.authority.state["verification_keys"]
        if (item["key_id"], item["key_version"])
        == (record["signed_plan"]["key_id"], record["signed_plan"]["key_version"])
    )
    before = _census(runtime)
    original = runtime.store.successor_latest_usage(record["attempt_id"])
    proposed = deepcopy(original)
    proposed["revision"] += 1
    proposed["previous_revision"] = original["revision"]
    runtime.authority.set_historical_access(
        identity,
        read=False,
        write=False,
        resume=False,
        observed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    denied_read = _post_status(runtime, {"submission_id": sid}, _headers(runtime))
    after_read_denial = _census(runtime)
    runtime.authority.set_historical_access(
        identity,
        read=True,
        write=True,
        resume=True,
        observed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    allowed_read = _post_status(runtime, {"submission_id": sid}, _headers(runtime))
    started = threading.Event()
    result = {}

    def late_writer():
        trusted = _authenticated(runtime)
        started.set()
        try:
            result["value"] = runtime.successor.ingest_usage_revision(sid, proposed, trusted)
        except BaseException as exc:
            result["error_type"] = type(exc).__name__

    with runtime.authority.gate:
        worker = threading.Thread(target=late_writer, daemon=True)
        worker.start()
        if not started.wait(5):
            raise TimeoutError("authenticated historical writer did not reach gate")
        runtime.authority.set_historical_access(
            identity,
            read=True,
            write=False,
            resume=False,
            observed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    worker.join(5)
    if worker.is_alive():
        raise TimeoutError("revoked-during-wait historical writer stuck")
    after_wait = _census(runtime)
    try:
        runtime.successor.resume_campaign(sid, _authenticated(runtime), "synthetic denied resume")
    except PermissionError:
        denied_resume = True
    else:
        denied_resume = False
    runtime.authority.set_historical_access(
        identity,
        read=True,
        write=True,
        resume=True,
        observed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    allowed_append = runtime.successor.ingest_usage_revision(sid, proposed, _authenticated(runtime))
    retained = runtime.successor.status(sid, _authenticated(runtime))
    after = _census(runtime)
    checks = {
        "ct02_historical_auth.read_denial": (
            bool(
                denied_read["http_status"] == 404
                and allowed_read["http_status"] == 200
                and after_read_denial == before
            ),
            "Current denied read was non-enumerating and did not mutate historical state",
        ),
        "ct02_historical_auth.wait_revocation": (
            bool(
                result.get("error_type") in {"PermissionError", "ContractError"}
                and after_wait["usage_revisions"] == before["usage_revisions"]
                and after_wait["campaign"]["cumulative_reserved_decimal"]
                == before["campaign"]["cumulative_reserved_decimal"]
            ),
            "Freshly authenticated write was revoked while waiting on mutation gate",
        ),
        "ct02_historical_auth.post_expiry": (
            bool(
                key["eligibility"] == "revoked"
                and datetime.fromisoformat(
                    record["signed_plan"]["expires_at"].replace("Z", "+00:00")
                )
                < datetime.now(timezone.utc)
                and allowed_append == "accepted"
                and retained["attempts"][0]["usage_revision"]["revision"] == proposed["revision"]
            ),
            "Original expired/revoked signed send authority did not suppress permitted late finance",
        ),
        "ct02_historical_auth.no_resend": (
            bool(
                denied_resume
                and after["usage_revisions"] == before["usage_revisions"] + 1
                and after["receiver_arrivals"] == before["receiver_arrivals"]
                and after["campaign"]["possible_send_count"]
                == before["campaign"]["possible_send_count"]
                and after["campaign"]["cumulative_reserved_decimal"]
                == before["campaign"]["cumulative_reserved_decimal"]
            ),
            "Denied resume and authorized late append created no new attempt, send or reservation",
        ),
    }
    return _evidence(
        runtime,
        case,
        {
            "authority": {"key_eligibility": key["eligibility"], "revoked_during_wait": result},
            "settlement": {
                "revision_before": original["revision"],
                "revision_after": proposed["revision"],
            },
        },
        checks,
        {
            "submission_id": sid,
            "attempt_id": record["attempt_id"],
            "signed_plan_expires_at": record["signed_plan"]["expires_at"],
            "denied_read": denied_read,
            "allowed_read": allowed_read,
            "denied_resume": denied_resume,
            "wait_result": result,
            "allowed_append": allowed_append,
            "retained": retained,
            "before": before,
            "after_read_denial": after_read_denial,
            "after_wait": after_wait,
            "after": after,
        },
        record["attempt_id"],
    )


def _reporting(runtime, case):
    from tools.gateway.evidence.dev12_completion_operator_handlers import (
        _csv_finance_reconcile,
        _operator_client,
        _read,
    )

    before = _census(runtime)
    with _operator_client(runtime) as client:
        current = _read(client)
        exported_json = _read(client, export="json")
        exported_csv = _read(client, export="csv")
    after = _census(runtime)
    report = exported_json.get("report", {})
    rows = exported_csv.get("rows", [])
    reconciled, finance = (
        _csv_finance_reconcile(rows, report.get("attempts", []), report.get("total", {}))
        if (exported_json["status"] == exported_csv["status"] == 200)
        else (False, {})
    )
    fixture_result = (
        runtime.root.parent / "continue02-review" / "overbound-http-01" / "HTTP-OBSERVATION.json"
    )
    if not fixture_result.is_file() or fixture_result.is_symlink():
        raise AssertionError("retained zero-send imported HTTP fixture absent")
    imported = json.loads(fixture_result.read_text())
    source = runtime.root / "cases" / "case.t50_e.composed-historical.sqlite"
    imported_ok = (
        imported["fixture_source_sha256"] == sha256(source.read_bytes()).hexdigest()
        and imported["denied_http"] == 401
        and imported["authorized_login_http"] == 200
        and imported["json_http"] == imported["csv_http"] == imported["ui_asset_http"] == 200
        and imported["report"]["total"]["over_bound_attempts"] == 1
        and imported["csv_rows"][0]["amount_decimal"]
        == imported["report"]["attempts"][0]["amount_decimal"]
        and imported["campaign"]["paused"] is True
        and imported["campaign"]["possible_send_count"] == 0
    )
    checks = {
        "ct02_reporting.csv_finance": (
            bool(reconciled and current["report"]["total"] == report["total"]),
            "Independent CSV field and Decimal sum reconciliation matches current JSON",
        ),
        "ct02_reporting.historical_overbound_http": (
            bool(imported_ok),
            "Separate zero-send imported underbound fixture is unclamped and visible through authenticated HTTP",
        ),
        "ct02_reporting.read_only": (
            before == after,
            "Current and imported report reads changed no attempt, receiver or allowance",
        ),
    }
    return _evidence(
        runtime,
        case,
        {
            "operator": {
                "rows": len(rows),
                "known_usd": finance.get("csv_known_usd"),
                "imported_http": imported["json_http"],
            },
            "accounting": {
                "current_total": report.get("total", {}),
                "imported_total": imported["report"]["total"],
            },
        },
        checks,
        {
            "current": current,
            "json_export": exported_json,
            "csv_export": exported_csv,
            "financial_detail": finance,
            "imported_report_only": imported,
            "before": before,
            "after": after,
        },
        case["attempt_group"],
    )


def _authority_wait(runtime, case):
    """Final lower-wait activation, logical expiry and durable pause controls."""
    from ezllmrouter_server.store import encode

    outcomes = {}
    baseline = _census(runtime)
    control_request = _case_request(runtime, case)
    control_request["work_selector"]["step_id"] += ".control"
    control = _post(runtime, control_request, _headers(runtime))
    control_after = _census(runtime)
    for name in ("activation", "expiry", "pause"):
        request = _case_request(runtime, case)
        request["work_selector"]["step_id"] += "." + name
        before = _census(runtime)
        fired = []
        original_clock = runtime.allowance.wall_clock

        async def lower_wait(*, fired=fired, name=name, before=before):
            if fired:
                return
            fired.append(True)
            if name == "activation":
                runtime.authority.update(
                    lambda state: state.update(
                        {"activation": {"state": "tagged_fixture", "epoch": "epoch.synthetic.ct02"}}
                    ),
                    {
                        "kind": "ct02_activation_after_lower_wait",
                        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                )
            elif name == "expiry":
                expiry = datetime.fromisoformat(
                    before["campaign"]["expires_at"].replace("Z", "+00:00")
                ) + timedelta(seconds=1)
                runtime.allowance.wall_clock = lambda: expiry
            else:
                with runtime.authority.gate:

                    def pause(db):
                        runtime.allowance.pause_in_transaction(runtime.store.database, "authority")
                        db.execute(
                            "INSERT INTO dev12_campaign_audit(campaign_id,record) VALUES (?,?)",
                            (
                                runtime.allowance.campaign_id,
                                encode(
                                    {
                                        "kind": "ct02_authority_pause_after_lower_wait",
                                        "actor_id": "synthetic.test.operator",
                                        "observed_at": datetime.now(timezone.utc).strftime(
                                            "%Y-%m-%dT%H:%M:%SZ"
                                        ),
                                    }
                                ),
                            ),
                        )

                    runtime.store._transaction(lambda: pause(runtime.store.db))

        runtime.executor.first_write_wait = lower_wait
        try:
            response = _post(runtime, request, _headers(runtime))
        finally:
            runtime.executor.first_write_wait = None
            runtime.allowance.wall_clock = original_clock
            if name == "activation":
                runtime.authority.update(
                    lambda state: state.update(
                        {"activation": {"state": "absent", "reason": "not_yet_issued"}}
                    ),
                    {
                        "kind": "ct02_restore_absent_activation",
                        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                )
        after = _census(runtime)
        outcomes[name] = {
            "fired": bool(fired),
            "response": response,
            "before": before,
            "after": after,
            "arrival_delta": after["receiver_arrivals"] - before["receiver_arrivals"],
        }
    checks = {
        "ct02_authority_wait.positive": (
            bool(
                control["status"]
                and control["status"]["submission_state"] == "completed"
                and control_after["receiver_arrivals"] == baseline["receiver_arrivals"] + 1
            ),
            "Unchanged authority completed one guarded matched control",
        ),
        "ct02_authority_wait.activation": (
            bool(
                outcomes["activation"]["fired"]
                and outcomes["activation"]["response"]["status"]["submission_state"] == "failed"
                and outcomes["activation"]["arrival_delta"] == 0
            ),
            "Current activation changed after real lower wait and blocked old plan",
        ),
        "ct02_authority_wait.expiry": (
            bool(
                outcomes["expiry"]["fired"]
                and outcomes["expiry"]["response"]["status"]["submission_state"] == "failed"
                and outcomes["expiry"]["arrival_delta"] == 0
                and outcomes["expiry"]["after"]["campaign"]["expires_at"]
                == baseline["campaign"]["expires_at"]
            ),
            "Injected evaluation time crossed original campaign expiry without moving durable deadline",
        ),
        "ct02_authority_wait.pause": (
            bool(
                outcomes["pause"]["fired"]
                and outcomes["pause"]["response"]["status"]["submission_state"] == "failed"
                and outcomes["pause"]["arrival_delta"] == 0
                and outcomes["pause"]["after"]["campaign"]["paused"]
                and "authority" in outcomes["pause"]["after"]["campaign"]["pause_reasons"]
            ),
            "Durable authority pause after lower wait blocked first bytes and remained held",
        ),
    }
    return _evidence(
        runtime,
        case,
        {
            "authority": {
                "controls": list(outcomes),
                "final_paused": outcomes["pause"]["after"]["campaign"]["paused"],
            },
            "first_write": {
                "arrivals": {key: item["arrival_delta"] for key, item in outcomes.items()}
            },
        },
        checks,
        {
            "control": control,
            "baseline": baseline,
            "control_after": control_after,
            "outcomes": outcomes,
        },
        control["reply"].get("attempt_id", "none"),
    )


def _transport(runtime, case):
    """Fault the socket underneath the exact product OwnedTLSStream drain."""
    from tools.gateway.evidence.dev12_completion_fault_transport import (
        CompletionTLSHTTPTransport,
        CompletionTLSStream,
    )
    from ezllmrouter_server.gateway.owned_tls_sender_transport import OwnedTLSStream

    if CompletionTLSStream._drain is not OwnedTLSStream._drain:
        raise AssertionError("completion transport no longer executes product drain")
    baseline = _census(runtime)
    observations = {}

    def invoke(label, mode, on_block=None):
        request = _case_request(runtime, case)
        request["work_selector"]["step_id"] += "." + label
        fault = {"mode": mode, "fired": False, "observations": []}
        if on_block:
            fault["on_block"] = on_block
        before = _census(runtime)
        CompletionTLSHTTPTransport.fault = fault
        try:
            with patch("dev12_executor.OwnedSyntheticTLSHTTPTransport", CompletionTLSHTTPTransport):
                response = _post(runtime, request, _headers(runtime))
        finally:
            CompletionTLSHTTPTransport.fault = None
        after = _census(runtime)
        return {
            "request": request,
            "response": response,
            "fault": {key: value for key, value in fault.items() if key != "on_block"},
            "before": before,
            "after": after,
        }

    if case["variant"] == "would_block_revoke":
        positive = invoke("would.block.control", "would_block_once")
        fired = []

        def revoke():
            fired.append(True)
            runtime.authority.update(
                lambda state: state.update({"send_permission": False}),
                {
                    "kind": "ct02_would_block_revocation",
                    "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            )

        try:
            blocked = invoke("would.block.revoked", "would_block_once", revoke)
        finally:
            if fired:
                runtime.authority.update(
                    lambda state: state.update({"send_permission": True}),
                    {
                        "kind": "ct02_would_block_permission_restore",
                        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                )
        observations = {"positive": positive, "blocked": blocked}
        checks = {
            "ct02_transport.product_drain": (
                True,
                "Exact product OwnedTLSStream._drain ran with lower socket injection",
            ),
            "ct02_transport.would_block_positive": (
                bool(
                    positive["fault"]["fired"]
                    and "SOCKET_WOULD_BLOCK_BEFORE_FIRST_BYTE" in positive["fault"]["observations"]
                    and positive["response"]["status"]["submission_state"] == "completed"
                    and positive["after"]["receiver_arrivals"]
                    == positive["before"]["receiver_arrivals"] + 1
                ),
                "Unchanged authority resumed product drain after socket would-block",
            ),
            "ct02_transport.would_block_revoked": (
                bool(
                    fired
                    and blocked["fault"]["fired"]
                    and blocked["response"]["status"]["submission_state"] == "failed"
                    and blocked["after"]["receiver_arrivals"]
                    == blocked["before"]["receiver_arrivals"]
                ),
                "Revocation during would-block wait blocked bytes before local acceptance",
            ),
        }
        primary = positive["response"]["reply"].get("attempt_id", "none")
    else:
        partial = invoke("partial.unknown", "partial_after_first_bytes")
        observations = {"partial": partial}
        reply = partial["response"]
        sid = reply["reply"].get("handle", {}).get("submission_id")
        if not sid:
            raise AssertionError("partial write attempt not admitted")
        unknown = _census(runtime)
        collected = runtime.successor.collect_receiver_receipt(sid, _authenticated(runtime))
        status = runtime.successor.status(sid, _authenticated(runtime))
        resumed = runtime.successor.resume_campaign(
            sid, _authenticated(runtime), "same-attempt partial TLS receipt reviewed"
        )
        after = _census(runtime)
        observations["late"] = {
            "collection": collected,
            "status": status,
            "resume": resumed,
            "after": after,
        }
        checks = {
            "ct02_transport.product_drain": (
                True,
                "Exact product OwnedTLSStream._drain ran with lower socket injection",
            ),
            "ct02_transport.partial_unknown": (
                bool(
                    partial["fault"]["fired"]
                    and "SOCKET_ACCEPTED_ONE_TLS_BYTE" in partial["fault"]["observations"]
                    and reply["status"]["submission_state"] == "unknown"
                    and unknown["campaign"]["paused"]
                    and unknown["receiver_arrivals"] == partial["before"]["receiver_arrivals"] + 1
                ),
                "One local TLS byte created possible-send uncertainty and genuine receiver arrival",
            ),
            "ct02_transport.partial_no_replay": (
                bool(
                    collected == "accepted"
                    and resumed["decision"] == "resumed"
                    and after["campaign"]["possible_send_count"]
                    == unknown["campaign"]["possible_send_count"]
                    and after["receiver_arrivals"] == unknown["receiver_arrivals"]
                    and status["attempts"][0]["usage_revision"]["cost_status"] == "calculated"
                ),
                "Independent receipt settled original attempt with no replay or new reservation",
            ),
        }
        primary = reply["reply"].get("attempt_id", "none")
    final = _census(runtime)
    return _evidence(
        runtime,
        case,
        {
            "guard": {"ownership_delta": final["guard_ownership"] - baseline["guard_ownership"]},
            "first_write": {
                "product_drain": True,
                "observations": {
                    key: value["fault"]["observations"]
                    for key, value in observations.items()
                    if "fault" in value
                },
            },
            "receiver": {
                "arrival_delta": final["receiver_arrivals"] - baseline["receiver_arrivals"]
            },
        },
        checks,
        {"observations": observations, "before": baseline, "after": final},
        primary,
    )


def _authority_atomic(runtime, case):
    """Commit/publication ordering, definite rollback and fail-closed restart."""
    from ezllmrouter_server.successor_plan import execution_eligible

    before = _census(runtime)
    control_request = _case_request(runtime, case)
    control_request["work_selector"]["step_id"] += ".before"
    control = _post(runtime, control_request, _headers(runtime))
    control_sid = control["reply"].get("handle", {}).get("submission_id")
    if not control_sid or control["status"]["submission_state"] != "completed":
        raise AssertionError("authority order control did not complete")
    old = runtime.store.successor_get(control_sid)
    original_revision = runtime.authority.revisions()["grant"]
    original_transaction = runtime.store._transaction

    class DefiniteRollback(RuntimeError):
        ezllmrouter_definite_rollback = True

    def fail_definitely(_action):
        raise DefiniteRollback("synthetic rollback before durable commit")

    runtime.store._transaction = fail_definitely
    try:
        try:
            runtime.authority.update(
                lambda state: state["revisions"].__setitem__(
                    "grant", state["revisions"]["grant"] + 1
                ),
                {"kind": "ct02_definite_rollback"},
            )
        except DefiniteRollback:
            rollback_caught = True
        else:
            rollback_caught = False
    finally:
        runtime.store._transaction = original_transaction
    rollback_revision = runtime.authority.revisions()["grant"]
    rollback_coherent = not runtime.authority.revoked and rollback_revision == original_revision

    entered, release, read_done = threading.Event(), threading.Event(), threading.Event()
    order = []
    errors = []

    def stalled_transaction(action):
        order.append("gate_held_transaction_entered")
        entered.set()
        if not release.wait(5):
            raise TimeoutError("synthetic authority commit stall exceeded bound")
        result = original_transaction(action)
        order.append("durable_authority_audit_committed")
        return result

    original_publish = runtime.authority._publish

    def observed_publish(state):
        order.append("matching_view_published")
        return original_publish(state)

    runtime.store._transaction = stalled_transaction
    runtime.authority._publish = observed_publish

    def writer():
        try:
            runtime.authority.update(
                lambda state: state["revisions"].__setitem__(
                    "grant", state["revisions"]["grant"] + 1
                ),
                {"kind": "ct02_stalled_commit"},
            )
            order.append("update_acknowledged")
        except BaseException as exc:
            errors.append(type(exc).__name__)

    def reader():
        runtime.authority.revisions()
        order.append("reader_acquired_released_gate")
        read_done.set()

    try:
        commit_thread = threading.Thread(target=writer, daemon=True)
        commit_thread.start()
        if not entered.wait(5):
            raise TimeoutError("authority update never entered stalled transaction")
        read_thread = threading.Thread(target=reader, daemon=True)
        read_thread.start()
        reader_blocked = not read_done.wait(0.05)
        release.set()
        commit_thread.join(5)
        read_thread.join(5)
        if commit_thread.is_alive() or read_thread.is_alive():
            raise TimeoutError("authority gate stall did not resolve")
    finally:
        release.set()
        runtime.store._transaction = original_transaction
        runtime.authority._publish = original_publish
    stalled_revision = runtime.authority.revisions()["grant"]

    def fail_publish(_state):
        raise RuntimeError("synthetic publication interruption after commit")

    runtime.authority._publish = fail_publish
    try:
        try:
            runtime.authority.update(
                lambda state: state["revisions"].__setitem__(
                    "grant", state["revisions"]["grant"] + 1
                ),
                {"kind": "ct02_committed_unpublished"},
            )
        except RuntimeError:
            publication_failed = True
        else:
            publication_failed = False
    finally:
        runtime.authority._publish = original_publish
    with runtime.store._lock:
        durable = json.loads(
            runtime.store.db.execute(
                "SELECT state FROM dev12_authority WHERE authority_id='standalone.synthetic'"
            ).fetchone()[0]
        )
    revoked_before_restart = runtime.authority.revoked
    try:
        runtime.authority.snapshot_epoch()
    except PermissionError:
        denied_unpublished = True
    else:
        denied_unpublished = False
    before_restart = _census(runtime)
    restarted = runtime.restart_service()
    after_restart = _census(runtime)
    current = runtime.authority.current_context(
        old, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    old_ineligible = not execution_eligible(
        old["signed_plan"],
        old["request"],
        old["canonical_work"],
        old["admission_snapshot"],
        current,
    )
    new_request = _case_request(runtime, case)
    new_request["work_selector"]["step_id"] += ".after.restart"
    fresh = _post(runtime, new_request, _headers(runtime))
    after = _census(runtime)
    ordered = (
        not errors
        and reader_blocked
        and order[:3]
        == [
            "gate_held_transaction_entered",
            "durable_authority_audit_committed",
            "matching_view_published",
        ]
        and "update_acknowledged" in order
        and "reader_acquired_released_gate" in order
    )
    checks = {
        "ct02_authority_atomic.definite_rollback": (
            bool(rollback_caught and rollback_coherent),
            "Definite rollback retained old coherent verification and send view",
        ),
        "ct02_authority_atomic.stalled_commit": (
            bool(ordered and stalled_revision == original_revision + 1),
            "Gate blocked readers until authority/audit commit, matching publication and acknowledgement",
        ),
        "ct02_authority_atomic.unpublished": (
            bool(
                publication_failed
                and revoked_before_restart
                and denied_unpublished
                and durable["revisions"]["grant"] == stalled_revision + 1
            ),
            "Committed but unpublished revision failed closed before any new send",
        ),
        "ct02_authority_atomic.restart": (
            bool(
                restarted["campaign_before"]["attempt_count"]
                == restarted["campaign_after"]["attempt_count"]
                and before_restart["receiver_arrivals"] == after_restart["receiver_arrivals"]
                and runtime.authority.revisions()["grant"] == durable["revisions"]["grant"]
                and old_ineligible
                and fresh["status"]["submission_state"] == "completed"
                and after["receiver_arrivals"] == after_restart["receiver_arrivals"] + 1
            ),
            "Same-campaign restart loaded durable authority and fresh current plan sent once",
        ),
    }
    return _evidence(
        runtime,
        case,
        {
            "authority": {
                "ordered_events": order,
                "durable_grant_revision": durable["revisions"]["grant"],
                "revoked_before_restart": revoked_before_restart,
            },
            "persistence": {"restart": restarted},
            "receiver": {"new_arrivals": after["receiver_arrivals"] - before["receiver_arrivals"]},
        },
        checks,
        {
            "control": control,
            "fresh": fresh,
            "old_plan": old["signed_plan"],
            "order": order,
            "errors": errors,
            "rollback_caught": rollback_caught,
            "publication_failed": publication_failed,
            "denied_unpublished": denied_unpublished,
            "before": before,
            "before_restart": before_restart,
            "after_restart": after_restart,
            "after": after,
            "durable_authority": durable,
        },
        fresh["reply"].get("attempt_id", "none"),
    )


def _realized_guard(runtime, case):
    """Mutate the actual HTTPX request immediately above the product guard."""
    import httpx

    variant = case["variant"]
    choices = {
        "method_host_route": ("method", "host", "route"),
        "headers_body": ("authorization", "missing_content_type", "extra_header", "body"),
        "timeout_matrix": ("changed", "missing", "extra", "nonfinite", "wrong_type"),
    }[variant]

    def transform_for(name):
        def change(request):
            method = "PUT" if name == "method" else request.method
            url = request.url
            if name == "host":
                url = httpx.URL(str(url).replace("synthetic.invalid", "other.invalid"))
            if name == "route":
                url = httpx.URL(str(url).replace("/synthetic/v1/embeddings", "/synthetic/v1/other"))
            headers = dict(request.headers)
            if name == "authorization":
                headers["Authorization"] = "Bearer synthetic-wrong"
            if name == "missing_content_type":
                headers.pop("content-type", None)
            if name == "extra_header":
                headers["x-unapproved"] = "synthetic"
            body = request.content + (b" " if name == "body" else b"")
            extensions = deepcopy(request.extensions)
            if name in {"changed", "missing", "extra", "nonfinite", "wrong_type"}:
                timeout = deepcopy(extensions["timeout"])
                if name == "changed":
                    timeout["connect"] = 4.9
                elif name == "missing":
                    del timeout["connect"]
                elif name == "extra":
                    timeout["total"] = 5
                elif name == "nonfinite":
                    timeout["connect"] = float("nan")
                else:
                    timeout["connect"] = "5"
                extensions["timeout"] = timeout
            return httpx.Request(method, url, headers=headers, content=body, extensions=extensions)

        return change

    baseline = _census(runtime)
    observations = {}
    for name in choices:
        request = _case_request(runtime, case)
        request["work_selector"]["step_id"] += "." + name
        before = _census(runtime)
        runtime.executor.realized_request_transform = transform_for(name)
        try:
            response = _post(runtime, request, _headers(runtime))
        finally:
            runtime.executor.realized_request_transform = None
        after = _census(runtime)
        observations[name] = {
            "response": response,
            "before": before,
            "after": after,
            "guard_delta": after["guard_ownership"] - before["guard_ownership"],
            "receiver_delta": after["receiver_arrivals"] - before["receiver_arrivals"],
        }
    control_request = _case_request(runtime, case)
    control_request["work_selector"]["step_id"] += ".matched.control"
    control_before = _census(runtime)
    control = _post(runtime, control_request, _headers(runtime))
    final = _census(runtime)
    observations["matched_control"] = {
        "response": control,
        "guard_delta": final["guard_ownership"] - control_before["guard_ownership"],
        "receiver_delta": final["receiver_arrivals"] - control_before["receiver_arrivals"],
    }
    checks = {}
    for name in choices:
        item = observations[name]
        checks[f"ct02_realized_guard.{name}"] = (
            bool(
                item["response"]["status"]
                and item["response"]["status"].get("submission_state") == "failed"
                and item["guard_delta"] == item["receiver_delta"] == 0
            ),
            "Actual realized request was rejected by the product guard before commit or receiver bytes",
        )
    checks["ct02_realized_guard.matched_control"] = (
        bool(
            control["status"]
            and control["status"].get("submission_state") == "completed"
            and observations["matched_control"]["guard_delta"] == 1
            and observations["matched_control"]["receiver_delta"] == 1
        ),
        "Unchanged realized request passed the same product guard and reached the receiver once",
    )
    return _evidence(
        runtime,
        case,
        {
            "guard": {
                "tested": list(choices),
                "commits": final["guard_ownership"] - baseline["guard_ownership"],
            },
            "first_write": {"arrivals": final["receiver_arrivals"] - baseline["receiver_arrivals"]},
        },
        checks,
        {"observations": observations, "before": baseline, "after": final},
        control["reply"].get("attempt_id", "none"),
    )


def supplement(runtime, case):
    pair = (case["scenario_id"], case["variant"])
    if pair[0] == "ct02_workkey":
        return _workkey(runtime, case)
    if pair[0] == "ct02_recovery":
        return _recovery(runtime, case)
    if pair[0] == "ct02_failed_unknown":
        return _failed_unknown(runtime, case)
    if pair[0] == "ct02_revision33":
        return _revision33(runtime, case)
    if pair[0] == "ct02_historical_auth":
        return _historical_auth(runtime, case)
    if pair[0] == "ct02_reporting":
        return _reporting(runtime, case)
    if pair[0] == "ct02_authority_wait":
        return _authority_wait(runtime, case)
    if pair[0] == "ct02_transport":
        return _transport(runtime, case)
    if pair[0] == "ct02_authority_atomic":
        return _authority_atomic(runtime, case)
    if pair[0] == "ct02_realized_guard":
        return _realized_guard(runtime, case)
    raise NotImplementedError(f"supplement handler incomplete: {pair}")
