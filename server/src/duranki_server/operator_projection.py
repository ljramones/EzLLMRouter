"""Allowlisted, read-only operator metadata over the trusted SQLite store."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re


ID = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
STATES = frozenset({"admitted", "completed", "failed_before_transmit",
                    "failed_after_transmit", "outcome_unknown"})


def _identifier(value):
    return value if type(value) is str and ID.fullmatch(value) else None


def _usage(raw):
    if raw is None:
        return {"state": "not_recorded", "cost": {"status": "unknown"},
                "price_version": None}
    value = json.loads(raw)
    normalized = value.get("normalized_usage", {})
    counts = {}
    knowledge = {}
    for name in ("input_total", "input_uncached", "input_cache_read", "input_cache_write",
                 "input_cache_write_30m", "input_cache_write_12h",
                 "output_total", "output_text", "output_reasoning"):
        item = normalized.get(name, {})
        count = item.get("count") if item.get("state") == "known" else None
        counts[name] = count if type(count) is int and count >= 0 else None
        knowledge[name] = item.get("state", "unknown")
    cost = value.get("cost", {})
    status = cost.get("status")
    safe_cost = {"status": status if status in ("unknown", "calculated", "reported", "reconciled")
                 else "unknown"}
    if safe_cost["status"] == "calculated" and cost.get("currency") == "USD" and \
            type(cost.get("amount_decimal")) is str:
        safe_cost.update(amount_decimal=cost["amount_decimal"], currency="USD",
                         label="calculated cost")
    return {"state": "available", "revision": value.get("revision"),
            "counts": counts, "knowledge": knowledge,
            "usage_semantics_version": value.get("usage_semantics_version"),
            "contract_version": value.get("contract_version"),
            "price_version": value.get("price_version"), "cost": safe_cost}


class OperatorProjection:
    def __init__(self, store, principal_id, send_events_path=None):
        self.store = store
        self.principal_id = principal_id
        self.send_events_path = Path(send_events_path) if send_events_path else None
        with store._lock:
            store.db.execute("""
                CREATE TABLE IF NOT EXISTS operator_launches (
                    operation_id TEXT PRIMARY KEY, kind TEXT NOT NULL,
                    state TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, submission_ids TEXT NOT NULL,
                    caller_lookups INTEGER NOT NULL, error_code TEXT
                )
            """)
            # An interrupted local launcher has no automatic replay path.
            store.db.execute("UPDATE operator_launches SET state='outcome_unknown' WHERE state='running'")
            store.db.execute("""
                CREATE TABLE IF NOT EXISTS operator_provider_validations (
                    operation_id TEXT PRIMARY KEY, connection_id TEXT NOT NULL,
                    connection_revision INTEGER NOT NULL, configuration_ref TEXT NOT NULL,
                    configuration_revision INTEGER NOT NULL,
                    max_output_tokens INTEGER NOT NULL, state TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    submission_id TEXT, error_code TEXT
                )
            """)
            # A restarted operator never repeats an ambiguous external request.
            store.db.execute("UPDATE operator_provider_validations SET state='outcome_unknown' "
                             "WHERE state='running'")

    def _latest_usage(self, attempt_id):
        row = self.store.db.execute(
            "SELECT usage FROM usage_revisions WHERE attempt_id=? "
            "ORDER BY revision DESC LIMIT 1", (attempt_id,)).fetchone()
        return _usage(row[0] if row else None)

    def _summary(self, raw, intent_raw=None):
        record = json.loads(raw)
        intent = json.loads(intent_raw) if intent_raw else {}
        key = record["work_key"]
        failure = record.get("terminal_failure") or {}
        code = failure.get("code")
        return {
            "submission_id": _identifier(record.get("submission_id")),
            "principal_id": _identifier(record.get("principal_id")),
            "attempt_id": _identifier(record.get("attempt_id")),
            "configuration_ref": _identifier((intent.get("destination") or {}).get("configuration_ref")),
            "task_id": _identifier(key.get("task_id")),
            "step_id": _identifier(key.get("step_id")),
            "step_revision": key.get("step_revision") if type(key.get("step_revision")) is int else None,
            "execution_generation": _identifier(key.get("execution_generation")),
            "submission_state": record.get("submission_state") if record.get("submission_state") in STATES else "unavailable",
            "dispatch_state": record.get("dispatch_state") if record.get("dispatch_state") in
                {"prepared", "intent_persisted", "guard_committed", "failed_before_dispatch", "response_observed", "outcome_unknown"}
                else "unavailable",
            "candidate_access": record.get("candidate_access") if record.get("candidate_access") in
                {"not_yet_available", "present", "not_retained", "expired", "unavailable_due_failure"}
                else "unavailable",
            "content_store_allowed": record.get("content_store_allowed") is True,
            "updated_at": record.get("updated_at") if type(record.get("updated_at")) is str else None,
            "error_code": code if type(code) is str and re.fullmatch(r"[A-Z0-9_]{1,64}", code) else None,
        }

    def activity(self, *, page=1, limit=20, state=None, principal_id=None):
        if type(page) is not int or not 1 <= page <= 10000 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid pagination")
        if state is not None and state not in STATES:
            raise ValueError("invalid state filter")
        principal_id = self.principal_id if principal_id is None else principal_id
        where = "1=1" if principal_id == "*" else "s.principal_id=?"
        args = [] if principal_id == "*" else [principal_id]
        if state:
            where += " AND json_extract(s.record,'$.submission_state')=?"
            args.append(state)
        with self.store._lock:
            total = self.store.db.execute("SELECT COUNT(*) FROM submissions s WHERE " + where, args).fetchone()[0]
            rows = self.store.db.execute(
                "SELECT s.record,i.intent FROM submissions s LEFT JOIN intents i "
                "ON i.submission_id=s.submission_id WHERE " + where +
                " ORDER BY s.rowid DESC LIMIT ? OFFSET ?",
                (*args, limit, (page - 1) * limit)).fetchall()
        return {"page": page, "limit": limit, "total": total,
                "items": [self._summary(*row) for row in rows]}

    def detail(self, submission_id, principal_id=None):
        if not _identifier(submission_id):
            raise ValueError("invalid submission id")
        principal_id = self.principal_id if principal_id is None else principal_id
        with self.store._lock:
            row = self.store.db.execute(
                "SELECT record FROM submissions WHERE submission_id=?" +
                ("" if principal_id == "*" else " AND principal_id=?"),
                (submission_id,) if principal_id == "*" else (submission_id, principal_id)).fetchone()
            if not row:
                return None
            value = self._summary(row[0])
            stored = json.loads(row[0])
            value["provider_model_reported"] = _identifier(stored.get("provider_model_reported"))
            attempt = value["attempt_id"]
            intent_row = self.store.db.execute("SELECT intent FROM intents WHERE attempt_id=? AND submission_id=?",
                                               (attempt, submission_id)).fetchone()
            receipt_row = self.store.db.execute(
                "SELECT receipt FROM guard_dispatches WHERE attempt_id=? AND submission_id=?",
                (attempt, submission_id)).fetchone()
            value["usage"] = self._latest_usage(attempt)
        intent = json.loads(intent_row[0]) if intent_row else {}
        receipt = json.loads(receipt_row[0]) if receipt_row else {}
        destination = intent.get("destination") or {}
        value["configuration_ref"] = _identifier(destination.get("configuration_ref"))
        value["intent"] = {"present": bool(intent_row), "plan_id": _identifier(intent.get("plan_id")),
                           "committed_at": intent.get("committed_at") if type(intent.get("committed_at")) is str else None}
        value["selected_configuration"] = {
            name: _identifier(destination.get(name)) for name in
            ("configuration_ref", "service", "endpoint", "model", "model_version", "processing_region")}
        value["dispatch_receipt"] = {"present": bool(receipt_row),
            "body_sha256": receipt.get("body_sha256") if type(receipt.get("body_sha256")) is str and
            re.fullmatch(r"[0-9a-f]{64}", receipt["body_sha256"]) else None,
            "body_bytes": receipt.get("body_bytes") if type(receipt.get("body_bytes")) is int else None,
            "committed_at": receipt.get("committed_at") if type(receipt.get("committed_at")) is str else None}
        return value

    def _send_observations(self, attempt_ids):
        """Diagnostic first-write facts. Missing or conflicting rows remain unknown."""
        if self.send_events_path is None:
            return {}
        observations = {}
        try:
            with self.send_events_path.open(encoding="utf-8") as stream:
                for line in stream:
                    try:
                        row = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    attempt = row.get("attempt_id") if type(row) is dict else None
                    if not _identifier(attempt) or attempt not in attempt_ids:
                        continue
                    accepted = row.get("first_bytes_accepted_by_local_socket")
                    count = row.get("first_acceptance_events")
                    if type(accepted) is not bool or type(count) is not int or count != int(accepted):
                        observations[attempt] = None
                    elif attempt in observations:
                        observations[attempt] = None
                    else:
                        observations[attempt] = accepted
        except (OSError, UnicodeError):
            return {}
        return observations

    def usage(self, principal_id=None):
        principal_id = self.principal_id if principal_id is None else principal_id
        with self.store._lock:
            rows = self.store.db.execute(
                "SELECT s.record,i.intent,g.receipt FROM submissions s "
                "LEFT JOIN intents i ON i.submission_id=s.submission_id "
                "LEFT JOIN guard_dispatches g ON g.submission_id=s.submission_id " +
                ("" if principal_id == "*" else "WHERE s.principal_id=? ") +
                "ORDER BY s.rowid DESC LIMIT 10001",
                () if principal_id == "*" else (principal_id,)).fetchall()
            truncated = len(rows) > 10000
            rows = rows[:10000]
            summaries = [self._summary(raw, intent) for raw, intent, _ in rows]
            latest = [self._latest_usage(item["attempt_id"]) for item in summaries]
        observations = self._send_observations({item["attempt_id"] for item in summaries})
        groups = {}
        from decimal import Decimal
        known_cost = {}
        cost_unknown = 0
        for item, usage, (_, intent_raw, receipt_raw) in zip(summaries, latest, rows):
            cost = usage["cost"]
            if cost["status"] == "calculated" and cost.get("currency") == "USD":
                known_cost["USD"] = known_cost.get("USD", Decimal(0)) + Decimal(cost["amount_decimal"])
            else:
                cost_unknown += 1
            group = groups.setdefault(item["step_id"], {"step_id": item["step_id"],
                "attempts": 0, "intents_persisted": 0, "final_requests_committed": 0,
                "transmission_started_observed": 0, "no_first_write_observed": 0,
                "write_observation_unknown": 0, "usage_available": 0,
                "principal_ids": set(), "configuration_refs": set(),
                "input_tokens_known": 0, "output_tokens_known": 0,
                "input_unknown": 0, "output_unknown": 0})
            group["attempts"] += 1
            group["intents_persisted"] += intent_raw is not None
            group["final_requests_committed"] += receipt_raw is not None
            observed = observations.get(item["attempt_id"])
            group["transmission_started_observed"] += observed is True
            group["no_first_write_observed"] += observed is False
            group["write_observation_unknown"] += observed is None
            if item["principal_id"]:
                group["principal_ids"].add(item["principal_id"])
            if item["configuration_ref"]:
                group["configuration_refs"].add(item["configuration_ref"])
            group["usage_available"] += usage["state"] == "available"
            for name, total, unknown in (("input_uncached", "input_tokens_known", "input_unknown"),
                                         ("output_text", "output_tokens_known", "output_unknown")):
                count = usage.get("counts", {}).get(name)
                if count is None:
                    group[unknown] += 1
                else:
                    group[total] += count
        by_step = []
        for group in sorted(groups.values(), key=lambda x: x["step_id"] or ""):
            group["principal_ids"] = sorted(group["principal_ids"])
            group["configuration_refs"] = sorted(group["configuration_refs"])
            # The historical API field remains a receipt count, never a send count.
            group["dispatched"] = group["final_requests_committed"]
            by_step.append(group)
        return {"attempts": len(summaries),
                "intents_persisted": sum(x["intents_persisted"] for x in by_step),
                "final_requests_committed": sum(x["final_requests_committed"] for x in by_step),
                "transmission_started_observed": sum(x["transmission_started_observed"] for x in by_step),
                "no_first_write_observed": sum(x["no_first_write_observed"] for x in by_step),
                "write_observation_unknown": sum(x["write_observation_unknown"] for x in by_step),
                "dispatched": sum(x["dispatched"] for x in by_step),
                "usage_available": sum(x["usage_available"] for x in groups.values()),
                "usage_unknown": len(summaries)-sum(x["usage_available"] for x in groups.values()),
                "cost": {"known_subtotals": {currency: format(amount, "f") for currency, amount in
                                               known_cost.items()}, "unknown_attempts": cost_unknown,
                         "label": "synthetic calculated cost"}, "truncated": truncated,
                "by_step": by_step}

    def overview_counts(self, principal_id=None):
        principal_id = self.principal_id if principal_id is None else principal_id
        with self.store._lock:
            rows = self.store.db.execute("SELECT record FROM submissions" +
                                         ("" if principal_id == "*" else " WHERE principal_id=?"),
                                         () if principal_id == "*" else (principal_id,)).fetchall()
            counts = {"submissions": len(rows), "completed": 0, "known_failures": 0,
                      "unknown_outcomes": 0, "blocked_before_send": 0}
            for (raw,) in rows:
                state = json.loads(raw).get("submission_state")
                counts["completed"] += state == "completed"
                counts["known_failures"] += state in ("failed_before_transmit", "failed_after_transmit")
                counts["unknown_outcomes"] += state == "outcome_unknown"
                counts["blocked_before_send"] += state == "failed_before_transmit"
        return counts

    def begin_launch(self, operation_id, kind):
        if not _identifier(operation_id) or kind not in ("text", "tool", "no_store_text"):
            raise ValueError("invalid launch")
        at = datetime.now(timezone.utc).isoformat()
        def action():
            existing = self.store.db.execute(
                "SELECT kind FROM operator_launches WHERE operation_id=?", (operation_id,)).fetchone()
            if existing:
                if existing[0] != kind:
                    raise ValueError("operation kind conflict")
                return False
            if self.store.db.execute("SELECT COUNT(*) FROM operator_launches WHERE state='running'").fetchone()[0]:
                raise ValueError("another synthetic launcher is running")
            self.store.db.execute("INSERT INTO operator_launches VALUES (?,?,?,?,?,?,?,?)",
                (operation_id, kind, "running", at, at, "[]", 0, None))
            return True
        return self.store._transaction(action)

    def finish_launch(self, operation_id, state, submission_ids, lookups=0, error_code=None):
        if state not in ("completed", "failed", "outcome_unknown") or type(lookups) is not int:
            raise ValueError("invalid launch result")
        ids = [x for x in submission_ids if _identifier(x)]
        with self.store._lock:
            self.store.db.execute("UPDATE operator_launches SET state=?,updated_at=?,submission_ids=?,"
                "caller_lookups=?,error_code=? WHERE operation_id=?",
                (state, datetime.now(timezone.utc).isoformat(), json.dumps(ids), lookups,
                 error_code if type(error_code) is str and re.fullmatch(r"[A-Z0-9_]{1,64}", error_code) else None,
                 operation_id))

    def record_launch_submission(self, operation_id, submission_id):
        if not _identifier(operation_id) or not _identifier(submission_id):
            raise ValueError("invalid launcher submission")
        def action():
            row = self.store.db.execute("SELECT submission_ids FROM operator_launches WHERE operation_id=?",
                                        (operation_id,)).fetchone()
            if not row:
                raise ValueError("unregistered launcher")
            values = json.loads(row[0])
            if submission_id not in values:
                values.append(submission_id)
                self.store.db.execute("UPDATE operator_launches SET submission_ids=?,updated_at=? "
                    "WHERE operation_id=?", (json.dumps(values), datetime.now(timezone.utc).isoformat(),
                                            operation_id))
        self.store._transaction(action)

    def launch(self, operation_id):
        if not _identifier(operation_id):
            raise ValueError("invalid operation id")
        with self.store._lock:
            row = self.store.db.execute("SELECT kind,state,created_at,updated_at,submission_ids,caller_lookups,error_code "
                "FROM operator_launches WHERE operation_id=?", (operation_id,)).fetchone()
        if not row:
            return None
        return {"operation_id": operation_id, "kind": row[0], "state": row[1],
                "created_at": row[2], "updated_at": row[3],
                "submission_ids": json.loads(row[4]), "caller_lookups": row[5], "error_code": row[6],
                "in_progress": row[1] == "running"}

    def begin_provider_validation(self, operation_id, connection_id, connection_revision,
                                  configuration_ref, configuration_revision, max_output_tokens):
        if (not all(_identifier(x) for x in (operation_id, connection_id, configuration_ref)) or
                type(connection_revision) is not int or connection_revision < 1 or
                type(configuration_revision) is not int or configuration_revision < 1 or
                type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 32):
            raise ValueError("invalid provider validation")
        at = datetime.now(timezone.utc).isoformat()
        def action():
            existing = self.store.db.execute(
                "SELECT connection_id,connection_revision,configuration_ref,configuration_revision,max_output_tokens "
                "FROM operator_provider_validations WHERE operation_id=?", (operation_id,)).fetchone()
            if existing:
                if existing != (connection_id, connection_revision, configuration_ref,
                                configuration_revision, max_output_tokens):
                    raise ValueError("provider validation operation conflict")
                return False
            if self.store.db.execute("SELECT 1 FROM operator_provider_validations WHERE state='running' LIMIT 1").fetchone():
                raise ValueError("provider validation already running")
            self.store.db.execute("INSERT INTO operator_provider_validations VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (operation_id, connection_id, connection_revision, configuration_ref, configuration_revision,
                 max_output_tokens, "running", at, at, None, None))
            return True
        return self.store._transaction(action)

    def record_provider_validation_submission(self, operation_id, submission_id):
        if not _identifier(operation_id) or not _identifier(submission_id):
            raise ValueError("invalid provider validation handle")
        with self.store._lock:
            self.store.db.execute("UPDATE operator_provider_validations SET submission_id=?,updated_at=? "
                "WHERE operation_id=? AND state='running'", (submission_id,
                    datetime.now(timezone.utc).isoformat(), operation_id))

    def finish_provider_validation(self, operation_id, state, error_code=None):
        if not _identifier(operation_id) or state not in ("completed", "failed", "outcome_unknown"):
            raise ValueError("invalid provider validation result")
        with self.store._lock:
            self.store.db.execute("UPDATE operator_provider_validations SET state=?,updated_at=?,error_code=? "
                "WHERE operation_id=? AND state='running'", (state,
                    datetime.now(timezone.utc).isoformat(),
                    error_code if type(error_code) is str and re.fullmatch(r"[A-Z0-9_]{1,64}", error_code) else None,
                    operation_id))

    def provider_validation(self, operation_id):
        if not _identifier(operation_id):
            raise ValueError("invalid provider validation operation")
        with self.store._lock:
            row = self.store.db.execute("SELECT connection_id,connection_revision,configuration_ref,configuration_revision,"
                "max_output_tokens,state,created_at,updated_at,submission_id,error_code "
                "FROM operator_provider_validations WHERE operation_id=?", (operation_id,)).fetchone()
        if not row:
            return None
        return {"operation_id": operation_id, "connection_id": row[0],
                "connection_revision": row[1], "configuration_ref": row[2],
                "configuration_revision": row[3], "max_output_tokens": row[4],
                "state": row[5], "created_at": row[6], "updated_at": row[7],
                "submission_id": row[8], "error_code": row[9]}
