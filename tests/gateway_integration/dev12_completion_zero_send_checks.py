"""Real SQLite rollback and gate-wait checks on a private copy of retained work.

No sender, worker, receiver or new submission is constructed. The source DB
is opened read-only and backed up consistently; only the owned copy changes.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
from cryptography.hazmat.primitives import serialization
from duranki_server.core import Coordinator
from duranki_server.store import SQLiteStore
from duranki_server.successor_authority import SyntheticSuccessorAuthority
from duranki_server.successor_campaign import FiniteSuccessorCampaign
from duranki_server.successor_service import SuccessorService


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def table_state(store):
    with store._lock:
        names = [row[0] for row in store.db.execute("SELECT name FROM sqlite_master "
                 "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {name: {"rows": len(rows), "sha256": sha256(json.dumps(rows,
            ensure_ascii=True, separators=(",", ":"), default=str).encode()).hexdigest()}
            for name in names for rows in [store.db.execute(
                'SELECT * FROM "' + name + '" ORDER BY rowid').fetchall()]}


class ObservedGate:
    def __init__(self, held):
        self.held = held
        self.worker_id = None
        self.attempted = threading.Event()
        self.attempt_ns = None

    def __enter__(self):
        if threading.get_ident() == self.worker_id:
            self.attempt_ns = time.monotonic_ns()
            self.attempted.set()
        self.held.__enter__()
        return self

    def __exit__(self, *args):
        return self.held.__exit__(*args)


def main(target, output):
    source = target / "campaign.sqlite"
    if output.exists() or not source.is_file() or source.is_symlink():
        raise ValueError("fresh owned output and retained source database required")
    source_before = digest(source)
    receiver_before = digest(target / "receiver.jsonl")
    output.mkdir(parents=True)
    copy = output / "private-retained-copy.sqlite"
    with sqlite3.connect("file:" + str(source) + "?mode=ro", uri=True) as original:
        with sqlite3.connect(copy) as destination:
            original.backup(destination)
    store = SQLiteStore(copy)
    with store._lock:
        state = json.loads(store.db.execute("SELECT state FROM dev12_authority "
            "WHERE authority_id='standalone.synthetic'").fetchone()[0])
    selector = state["active_minting_key"]
    key_path = target / ("signing-key-" + selector["key_version"] + ".pem")
    if selector["key_version"] == "v1":
        key_path = target / "signing-key.pem"
    private = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    authority = SyntheticSuccessorAuthority(store, private, selector["key_id"], selector["key_version"])
    campaign = FiniteSuccessorCampaign(store, "campaign.dev12.c02.20261026.continue01",
        "budget.dev12.c02.20261026.continue01",
        financial_owner_id="team.dev12.c02.20261026.continue01")
    assert campaign.inspect()["paused"] and "authority" in campaign.inspect()["pause_reasons"]
    before = table_state(store)
    published_before = deepcopy(authority.state)
    epoch_before = authority.epoch
    trace = []
    store.db.set_trace_callback(lambda sql: trace.append(sql.lstrip().split(None, 1)[0].upper()))
    original_transaction = store._transaction
    staged = {}

    class StagedFailure(RuntimeError):
        pass

    def real_staged_failure(action):
        def stage_then_fail():
            action()  # real authority and audit SQL, inside real BEGIN IMMEDIATE
            durable = json.loads(store.db.execute("SELECT state FROM dev12_authority "
                "WHERE authority_id='standalone.synthetic'").fetchone()[0])
            audit_rows = store.db.execute("SELECT COUNT(*) FROM dev12_authority_audit").fetchone()[0]
            staged.update({"grant_revision": durable["revisions"]["grant"],
                           "audit_rows": audit_rows})
            assert staged["grant_revision"] == published_before["revisions"]["grant"] + 1
            assert audit_rows == before["dev12_authority_audit"]["rows"] + 1
            raise StagedFailure("injected after both real staged writes")
        return original_transaction(stage_then_fail)

    store._transaction = real_staged_failure
    try:
        try:
            authority.update(lambda next_state: next_state["revisions"].__setitem__(
                "grant", next_state["revisions"]["grant"] + 1),
                {"kind": "ct02_actual_staged_rollback", "at": utc()})
        except StagedFailure as exc:
            definite = getattr(exc, "duranki_definite_rollback", False)
        else:
            raise AssertionError("staged authority failure committed unexpectedly")
    finally:
        store._transaction = original_transaction
        store.db.set_trace_callback(None)
    rollback_after = table_state(store)
    if (not definite or not staged or "BEGIN" not in trace or "UPDATE" not in trace or
        "INSERT" not in trace or "ROLLBACK" not in trace or "COMMIT" in trace or
        before != rollback_after or authority.state != published_before or
        authority.epoch != epoch_before or authority.revoked):
        raise AssertionError("actual staged rollback/coherent view not established")
    rollback = {"status": "PASS", "definite_rollback_from_store": definite,
        "staged_before_failure": staged, "sql_operations": trace,
        "all_table_hashes_before": before, "all_table_hashes_after": rollback_after,
        "published_epoch_before_after": [epoch_before, authority.epoch],
        "published_view_unchanged": True}

    # Select an actual completed same-campaign attempt with accepted known
    # native usage. Its next revision is a re-adjudication of retained evidence.
    with store._lock:
        records = [json.loads(row[0]) for row in store.db.execute(
            "SELECT record FROM dev12_submissions WHERE "
            "json_extract(record,'$.work_key.principal_id')='user.demo' "
            "AND json_extract(record,'$.submission_state')='completed' ORDER BY rowid")]
    selected = next((row for row in records if row["campaign_id"] == campaign.campaign_id and
        (latest := store.successor_latest_usage(row["attempt_id"])) and
        latest["cost_status"] == "calculated"), None)
    if selected is None:
        raise AssertionError("retained known-cost historical attempt absent")
    sid, attempt = selected["submission_id"], selected["attempt_id"]
    latest = store.successor_latest_usage(attempt)
    proposed = deepcopy(latest)
    proposed["revision"] += 1
    proposed["previous_revision"] = latest["revision"]
    token = "dev12.continue03.disposable.read." + "x" * 24
    trusted = {**selected["trusted_identity"], "task_id": selected["work_key"]["task_id"],
               "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).strftime(
                   "%Y-%m-%dT%H:%M:%SZ")}
    coordinator = Coordinator(None, {token: trusted}, {}, {}, {}, None, None, {}, {}, None)
    authenticated = coordinator.authenticate(token)
    assert authenticated == trusted
    service = SuccessorService(store, {}, authority, object(), campaign,
        read_allowed=lambda _who, _record: True,
        usage_write_allowed=lambda _who, _record: True)
    observed_gate = ObservedGate(authority.gate)
    authority.gate = observed_gate
    grant_before = authority.state["historical_access_revision"]
    denied_before = table_state(store)
    result = {}

    def worker():
        observed_gate.worker_id = threading.get_ident()
        try:
            result["value"] = service.ingest_usage_revision(sid, proposed,
                coordinator.authenticate(token))
        except BaseException as exc:
            result["error_type"] = type(exc).__name__
            result["error_text"] = str(exc)

    try:
        with authority.gate:
            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            if not observed_gate.attempted.wait(5):
                raise TimeoutError("historical worker did not attempt held product gate")
            assert thread.is_alive()
            wait_attempt_ns = observed_gate.attempt_ns
            authority.set_historical_access(selected["trusted_identity"], read=True,
                write=False, resume=False, observed_at=utc())
            revoke_done_ns = time.monotonic_ns()
        thread.join(timeout=5)
        if thread.is_alive() or result.get("error_type") != "PermissionError":
            raise AssertionError("after-wait historical permission denial absent")
        denied_after = table_state(store)
        invariant_tables = set(denied_before) - {"dev12_authority", "dev12_authority_audit"}
        if any(denied_before[name] != denied_after[name] for name in invariant_tables):
            raise AssertionError("denied historical write changed non-authority state")
        assert authority.state["historical_access_revision"] == grant_before + 1
        assert store.successor_latest_usage(attempt) == latest
        denied = {"status": "PASS", "submission_id": sid, "attempt_id": attempt,
            "accepted_predecessor_revision": latest["revision"],
            "gate_attempt_observed_before_revoke": wait_attempt_ns < revoke_done_ns,
            "worker_blocked_while_gate_held": True,
            "denial": result, "non_authority_table_hashes_unchanged": True,
            "before": denied_before, "after": denied_after,
            "grant_revision_before_after": [grant_before,
                                             authority.state["historical_access_revision"]]}

        authority.set_historical_access(selected["trusted_identity"], read=True,
            write=True, resume=True, observed_at=utc())
        positive_before = table_state(store)
        observed_gate.attempted.clear()
        positive_result = {}

        def positive_worker():
            observed_gate.worker_id = threading.get_ident()
            try:
                positive_result["value"] = service.ingest_usage_revision(sid, proposed,
                    coordinator.authenticate(token))
            except BaseException as exc:
                positive_result["error_type"] = type(exc).__name__

        with authority.gate:
            positive_thread = threading.Thread(target=positive_worker, daemon=True)
            positive_thread.start()
            if not observed_gate.attempted.wait(5) or not positive_thread.is_alive():
                raise TimeoutError("positive historical worker did not wait at product gate")
        positive_thread.join(timeout=5)
        if positive_thread.is_alive() or positive_result != {"value": "accepted"}:
            raise AssertionError("unchanged-authority historical positive failed")
        positive_after = table_state(store)
        for name in ("dev12_campaigns", "dev12_campaign_attempts", "dev12_send_ownership",
                     "work_key_owners", "submissions", "intents", "guard_dispatches"):
            assert positive_before[name] == positive_after[name]
        assert positive_after["dev12_usage_revisions"]["rows"] == \
            positive_before["dev12_usage_revisions"]["rows"] + 1
        assert store.successor_latest_usage(attempt) == proposed
        assert campaign.inspect()["paused"] and "authority" in campaign.inspect()["pause_reasons"]
        positive = {"status": "PASS", "same_gate_attempt_observed": True,
            "result": positive_result, "revision_before_after": [latest["revision"], proposed["revision"]],
            "cost_status": proposed["cost_status"],
            "amount_decimal": proposed.get("amount_decimal"),
            "campaign_and_ownership_unchanged": True,
            "usage_rows_before_after": [positive_before["dev12_usage_revisions"]["rows"],
                                         positive_after["dev12_usage_revisions"]["rows"]]}
    finally:
        service.pool.shutdown(wait=True)
        coordinator.pool.shutdown(wait=True)
        store.close()
    assert digest(source) == source_before and digest(target / "receiver.jsonl") == receiver_before
    result_doc = {"kind": "dev12_completion02_continue03_zero_send_actual_store_v1",
        "source_database_sha256": source_before, "receiver_log_sha256": receiver_before,
        "copy_database_sha256_after": digest(copy),
        "source_database_and_receiver_unchanged": True,
        "sender_worker_receiver_started": False,
        "new_admissions_or_possible_sends": 0,
        "rollback": rollback, "gate_wait_denial": denied, "gate_wait_positive": positive}
    (output / "OBSERVATION.json").write_text(json.dumps(result_doc, sort_keys=True,
        indent=2, ensure_ascii=True) + "\n")
    print(json.dumps({"status": "PASS", "rollback": rollback["status"],
        "gate_wait_denial": denied["status"], "gate_wait_positive": positive["status"],
        "source_unchanged": True}))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
