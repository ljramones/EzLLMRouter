"""Explicit wire-0.3 standalone service over authenticated synthetic contexts."""
from __future__ import annotations

from .observability import log_failure

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
import sqlite3
import time
import uuid

from .canonical import ContractError
from .successor_contract import (REGISTRATIONS, SCHEMAS, classify_request, digest,
                                 native_usage_row, result_valid, schema_valid,
                                 work_digest, work_projection)
from .successor_plan import execution_eligible, mint_plan


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def error_response(code, guidance=None):
    if guidance is None:
        guidance = "query_first" if code == "INTENT_PERSIST_FAILED" else "never"
    return {"contract_version": "0.3", "code": code,
            "correlation_id": "error." + uuid.uuid4().hex, "retry_guidance": guidance}


class SuccessorService:
    """Supported only when a qualified isolated executor and finite allowance are injected.

    Authentication remains the normal Coordinator's bearer check. The resolver
    supplies A1 trusted run/identity data from the authenticated credential,
    never from caller metadata. An absent executor/allowance cannot admit work.
    """

    def __init__(self, store, contexts_by_credential, authority, executor, allowance,
                 *, clock=utc_now, read_allowed=None, usage_write_allowed=None,
                 receiver_receipts=None):
        if read_allowed is None or usage_write_allowed is None:
            raise ValueError("explicit current successor read/write controls required")
        self.store = store
        self.contexts = contexts_by_credential
        self.authority = authority
        self.executor = executor
        self.allowance = allowance
        self.clock = clock
        self.read_allowed = read_allowed
        self.usage_write_allowed = usage_write_allowed
        self.receiver_receipts = receiver_receipts
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="duranki-dev12")
        self.futures = {}

    def _update(self, *args, **kwargs):
        # Authority/campaign writers and first-write checks take gate before DB.
        with self.authority.gate:
            return self.store.successor_update(*args, **kwargs)

    def recover_incomplete(self):
        """Never replay after restart; retain possible-send exposure durably."""
        with self.authority.gate:
            with self.store._lock:
                rows = [json.loads(row[0]) for row in self.store.db.execute(
                    "SELECT record FROM dev12_submissions WHERE json_extract(record,'$.submission_state')='pending' "
                    "AND json_extract(record,'$.campaign_id')=?", (self.allowance.campaign_id,))]
            for record in rows:
                sid, aid = record["submission_id"], record["attempt_id"]
                committed = self._send_committed(sid, aid)
                def settled(db):
                    if committed:
                        self.allowance.pause_in_transaction(db, "unknown_outcome")
                    self.allowance.finish(aid, db=db)
                if committed:
                    fields = {"submission_state": "unknown", "dispatch_state": "possible_send",
                              "delivery_state": "unknown", "candidate_access": "unknown_outcome"}
                else:
                    fields = {"submission_state": "failed", "dispatch_state": "blocked",
                              "delivery_state": "pending", "candidate_access": "unavailable_due_failure",
                              "failure_stage": "before_send", "failure": error_response("FDC_REJECTED")}
                self._update(sid, fields, self.clock(), on_update=settled)

    def _send_committed(self, sid, aid):
        with self.store._lock:
            return self.store.db.execute(
                "SELECT 1 FROM dev12_send_ownership WHERE submission_id=? AND attempt_id=?",
                (sid, aid)).fetchone() is not None

    def _possible_send(self, sid):
        return self._update(sid, {"submission_state": "unknown", "dispatch_state": "possible_send",
            "delivery_state": "unknown", "candidate_access": "unknown_outcome"}, self.clock(),
            on_update=lambda db: self.allowance.pause_in_transaction(db, "unknown_outcome"))

    def ingest_usage_revision(self, submission_id, usage, trusted):
        """Historical settlement needs current write authority, not send eligibility."""
        with self.authority.gate:
            # Recheck after any wait for the mutation gate. Authority writers
            # for this standalone profile use the same gate.
            record = self._visible(self.store.successor_get(submission_id), trusted)
            if record.get("campaign_id") != self.allowance.campaign_id:
                raise PermissionError("historical usage outside admitted campaign")
            allowed = (self.authority.historical_allowed(trusted, record, "write") and
                       self.usage_write_allowed(trusted, record))
            return self.store.successor_append_usage(submission_id, usage, self.clock(),
                write_allowed=allowed, on_settlement=lambda db, status:
                    self.allowance.pause_in_transaction(db,
                        "unknown_cost" if status == "unknown" else "over_bound")
                    if status in ("unknown", "over_bound") else None)

    def collect_receiver_receipt(self, submission_id, trusted):
        """Settle one admitted attempt from the receiver's retained observation."""
        if self.receiver_receipts is None:
            raise PermissionError("independent receiver receipt source unavailable")
        with self.authority.gate:
            record = self._visible(self.store.successor_get(submission_id), trusted)
            if (record.get("campaign_id") != self.allowance.campaign_id or
                    not self.authority.historical_allowed(trusted, record, "write") or
                    not self.usage_write_allowed(trusted, record)):
                raise PermissionError("historical receiver collection denied")
            aid = record["attempt_id"]
            with self.store._lock:
                ownership = self.store.db.execute(
                    "SELECT guard_receipt FROM dev12_send_ownership "
                    "WHERE attempt_id=? AND submission_id=?", (aid, submission_id)).fetchone()
                prior_receipts = [json.loads(row[0]) for row in self.store.db.execute(
                    "SELECT evidence FROM dev12_evidence_events WHERE submission_id=? "
                    "AND event_kind='late_receiver_receipt_collected'", (submission_id,))]
            if ownership is None:
                raise ValueError("guarded send ownership required for late collection")
            guard = json.loads(ownership[0])
            if (type(guard.get("body_sha256")) is not str or
                    type(guard.get("body_bytes")) is not int):
                raise ValueError("guard receipt lacks exact request binding")
            receipt, receipt_digest = self.receiver_receipts.find(aid,
                body_sha256=guard["body_sha256"], body_bytes=guard["body_bytes"],
                route=record["signed_plan"]["execution_descriptor"]["route"])
            if prior_receipts:
                if (len(prior_receipts) == 1 and
                        prior_receipts[0]["receipt_digest"] == receipt_digest):
                    return "duplicate"
                raise ValueError("conflicting retained receiver receipt")
            previous = self.store.successor_latest_usage(aid)
            if previous and previous["cost_status"] != "unknown":
                raise ValueError("known effective usage cannot be replaced by collection")
            usage = native_usage_row(record["request"], aid,
                previous["revision"] + 1 if previous else 1,
                receipt["usage_component"], record["reservation"]["max_exposure_decimal"],
                previous_revision=previous["revision"] if previous else None)
            event = {"receipt_digest": receipt_digest,
                     "receiver_received_at_ns": receipt["received_at_ns"],
                     "body_sha256": receipt["body_sha256"],
                     "body_bytes": receipt["body_bytes"],
                     "source_ref": receipt["usage_component"]["source_ref"],
                     "initial_observation": previous["cost_status"] if previous else "none"}
            return self.store.successor_append_usage(submission_id, usage, self.clock(),
                write_allowed=True, receipt_event=event,
                on_settlement=lambda db, status: self.allowance.pause_in_transaction(db,
                    "unknown_cost" if status == "unknown" else "over_bound")
                    if status in ("unknown", "over_bound") else None)

    def resume_campaign(self, submission_id, trusted, reason):
        """An authenticated synthetic actor requests an auditable eligibility decision."""
        if type(reason) is not str or not 1 <= len(reason) <= 160 or any(ord(c) < 32 for c in reason):
            raise ValueError("bounded resume reason required")
        with self.authority.gate:
            record = self._visible(self.store.successor_get(submission_id), trusted)
            if (record.get("campaign_id") != self.allowance.campaign_id or
                    not self.authority.historical_allowed(trusted, record, "resume")):
                raise PermissionError("audited resume denied")
            return self.allowance.resume(self.authority, actor_id=trusted["actor_id"],
                                         reason=reason, observed_at=self.clock())

    def _context(self, credential, legacy_trusted):
        context = self.contexts.get(credential)
        if (not context or not schema_valid(context, SCHEMAS["$defs"]["TrustedContext"]) or
                context["identity"]["principal_id"] != legacy_trusted["principal_id"] or
                context["identity"]["charging_owner_id"] != legacy_trusted["charging_owner_id"] or
                context["identity"]["source_authority_id"] != legacy_trusted["source_authority_id"] or
                not context["authenticated_at"] <= self.clock() < context["expires_at"]):
            raise ContractError("POLICY_DENIED", 403)
        return context

    def _visible(self, record, trusted):
        if (not record or record["work_key"]["principal_id"] != trusted["principal_id"] or
                record["work_key"]["task_id"] != trusted["task_id"] or
                not self.authority.historical_allowed(trusted, record, "read") or
                not self.read_allowed(trusted, record)):
            raise ContractError("NOT_FOUND_OR_FORBIDDEN", 404)
        return record

    def capabilities(self, _trusted):
        return {"contract_version": "0.3", "profile": "retrieval-synthetic@1",
                "supported_operations": ["embedding.create@1", "rerank@1"], "disabled_operations": []}

    @staticmethod
    def _handle(record):
        return {"contract_version": "0.3", "submission_id": record["submission_id"],
                "work_key": record["work_key"]}

    def _reply(self, record):
        common = {"contract_version": "0.3", "handle": self._handle(record),
                  "attempt_id": record["attempt_id"]}
        state = record["submission_state"]
        if state == "completed":
            if self._result_expired(record):
                error = ContractError("POLICY_DENIED", 403)
                error.retry_guidance = "query_first"
                raise error
            if record.get("result") is None:
                raise ContractError("RESULT_INVALID", 502)
            return 200, {**common, "state": "completed", "result": record["result"]}
        if state == "failed":
            status = (503 if record["failure_stage"] == "before_send" and
                      record["failure"]["code"] == "INTENT_PERSIST_FAILED" else
                      409 if record["failure_stage"] == "before_send" else 502)
            return status, {**common, "state": "failed", "failure_stage": record["failure_stage"],
                            "error": record["failure"]}
        if state == "unknown":
            return 202, {**common, "state": "outcome_unknown", "exposure_state": "retained"}
        return 202, {**common, "state": "pending", "pending_result_policy": "pollable_public_synthetic"}

    def _result_expired(self, record):
        if record.get("candidate_access") == "expired":
            return True
        origin = record.get("result_available_at")
        return bool(origin and datetime.fromisoformat(self.clock().replace("Z", "+00:00")) >=
                    datetime.fromisoformat(origin.replace("Z", "+00:00")) + timedelta(days=7))

    def submit(self, request, trusted, wait_ms, *, credential):
        if type(wait_ms) is not int or not 0 <= wait_ms <= 30000:
            raise ContractError("SCHEMA_INVALID", 400)
        context = self._context(credential, trusted)
        if type(request) is not dict or type(request.get("work_selector")) is not dict:
            raise ContractError("SCHEMA_INVALID", 400)
        if request["work_selector"].get("task_id") != trusted["task_id"]:
            raise ContractError("POLICY_DENIED", 403)
        classification = classify_request(request, context, fresh=False)
        if classification != "ACCEPT":
            status = 400 if classification in ("SCHEMA_INVALID", "UNSUPPORTED_VERSION") else 422
            raise ContractError(classification, status)
        work = work_projection(request, context)
        work_hash = work_digest(work)
        key = work["work_key"]
        with self.authority.gate:
            prior = self.store.successor_by_work(key)
            if prior:
                self._visible(prior, trusted)
                if prior["work_digest"] != work_hash:
                    raise ContractError("WORK_CONFLICT", 409)
                return self._reply(prior)
        owner = self.store.work_owner(key)
        if owner and owner["contract_version"] != "0.3":
            raise ContractError("WORK_VERSION_CONFLICT", 409)
        if classify_request(request, context) != "ACCEPT":
            raise ContractError("SEMANTIC_INVALID", 422)
        if self.executor is None or self.allowance is None:
            raise ContractError("FINANCIAL_AUTH_REQUIRED", 403)
        sid, aid = "submission." + uuid.uuid4().hex, "attempt." + uuid.uuid4().hex
        assessed_at = self.clock()
        commission = request["metadata"].get("commission")
        if commission and commission["kind"] == "asserted":
            commission_assessment = {"status": "asserted", "evidence_scope": "record_only"}
        else:
            absence_reason = "caller_omitted" if commission is None else "not_applicable"
            commission_assessment = {"status": "absent", "evidence_scope": "none",
                                     "absence_reason": absence_reason}
        delegation = request["metadata"]["delegation"]
        admission = {"snapshot_version": "dev12-admission@1", "work_digest": work_hash,
                     "assessed_at": assessed_at, "commission": commission_assessment,
                     "delegation": {"coverage": "none", "verified_link_indices": [],
                                    "absence_reason": "unavailable" if delegation else "not_applicable"}}
        if not schema_valid(admission, SCHEMAS["$defs"]["AdmissionSnapshot"]):
            raise ContractError("SEMANTIC_INVALID", 422)
        admission_hash = digest("duranki-admission-v1\n", admission)
        with self.authority.gate:
            revisions, activation, key_id, key_version, signer = self.authority.minting_snapshot()
            plan = mint_plan(request, work_hash, admission_hash, sid, aid,
                             context["identity"]["charging_owner_id"],
                             self.allowance.budget_account_id, revisions,
                             activation, key_id, key_version, signer)
        record = {"contract_version": "0.3", "submission_id": sid, "attempt_id": aid,
                  "work_key": key, "work_digest": work_hash, "canonical_work": work,
                  "request": request, "admission_snapshot": admission,
                  "admission_snapshot_digest": admission_hash, "signed_plan": plan,
                  "reservation": plan["reservation"], "trusted_identity": context["identity"],
                  "trusted_context": context,
                  "created_at": assessed_at, "updated_at": assessed_at,
                  "submission_state": "pending", "dispatch_state": "reserved",
                  "delivery_state": "pending", "settlement_state": "pending",
                  "candidate_access": "not_yet_available", "exposure_state": "outstanding",
                  "status_revision": 1}
        # An inert, private test seam can synchronize contenders immediately
        # before the real authority gate and transactional WorkKey claim.
        probe = getattr(self, "_before_first_ownership", None)
        if probe is not None:
            probe(key, record)
        try:
            with self.authority.gate:
                self.store.successor_create(record, reserve=self.allowance.reserve)
        except sqlite3.IntegrityError:
            owner = self.store.work_owner(key)
            if owner and owner["contract_version"] != "0.3":
                raise ContractError("WORK_VERSION_CONFLICT", 409) from None
            concurrent = self.store.successor_by_work(key)
            if concurrent and concurrent["work_digest"] == work_hash:
                return self._reply(self._visible(concurrent, trusted))
            raise ContractError("WORK_CONFLICT", 409) from None
        except (ValueError, PermissionError) as exc:
            raise ContractError("FINANCIAL_AUTH_REQUIRED", 403) from exc
        future = self.pool.submit(self._execute, record, trusted)
        self.futures[sid] = future
        remaining = max(0, (datetime.fromisoformat(request["deadline"].replace("Z", "+00:00")) -
                            datetime.now(timezone.utc)).total_seconds())
        try:
            future.result(timeout=min(wait_ms / 1000, remaining))
        except TimeoutError:
            pass
        except Exception:
            log_failure('successor_service.SuccessorService.submit.failed')
            # The durable row/intent controls recovery; no second invocation.
            pass
        return self._reply(self.store.successor_get(sid))

    def _execute(self, record, trusted):
        sid, aid = record["submission_id"], record["attempt_id"]
        response_observed = False
        try:
            current = self.authority.current_context(record, self.clock())
            if not execution_eligible(record["signed_plan"], record["request"],
                                      record["canonical_work"], record["admission_snapshot"], current):
                raise ContractError("PLAN_INVALID_OR_STALE", 409)
            outcome = self.executor.execute(record, self.authority, self.store, self.allowance)
            if outcome["state"] == "unknown":
                self._possible_send(sid)
                return
            with self.store._lock:
                committed = self.store.db.execute(
                    "SELECT 1 FROM dev12_send_ownership WHERE attempt_id=?", (aid,)).fetchone()
            if not committed:
                raise ContractError("FDC_REJECTED", 409)
            if outcome["state"] != "observed":
                raise ContractError("RESULT_INVALID", 502)
            response_observed = True
            if "usage_component" not in outcome:
                from .successor_contract import price_for
                component = {"component": price_for(record["request"])["component"], "presence": "absent"}
            elif outcome["usage_component"] is None:
                from .successor_contract import price_for
                component = {"component": price_for(record["request"])["component"], "presence": "null"}
            else:
                component = outcome["usage_component"]
            try:
                if type(component) is not dict:
                    raise ValueError("non-object native evidence")
                usage = native_usage_row(record["request"], aid, 1, component,
                                         record["reservation"]["max_exposure_decimal"])
            except (ValueError, KeyError, TypeError, AttributeError):
                from .successor_contract import price_for
                # JSON decoding permits escaped lone surrogates. ASCII escaping
                # makes the invalid-evidence digest total without changing the
                # canonical work or signing serializers.
                raw = json.dumps(component, sort_keys=True, ensure_ascii=True,
                                 separators=(",", ":")).encode("ascii")
                invalid = {"component": price_for(record["request"])["component"],
                           "presence": "invalid", "raw_digest": "sha256:" + sha256(raw).hexdigest()}
                usage = native_usage_row(record["request"], aid, 1, invalid,
                                         record["reservation"]["max_exposure_decimal"])
            with self.authority.gate:
                self.store.successor_append_usage(sid, usage, self.clock(),
                                                  # Committed sender evidence is an internal
                                                  # accounting write, not a caller late write.
                                                  write_allowed=True,
                                                  on_settlement=lambda db, status:
                                                      self.allowance.pause_in_transaction(db,
                                                          "unknown_cost" if status == "unknown" else "over_bound")
                                                      if status in ("unknown", "over_bound") else None)
            if outcome.get("http_status", 200) != 200 or not result_valid(
                    outcome.get("result"), record["request"], aid):
                raise ContractError("RESULT_INVALID", 502)
            self._update(sid, {"submission_state": "completed",
                                              "dispatch_state": "sent", "delivery_state": "valid",
                                              "candidate_access": "present", "result": outcome["result"],
                                              "result_available_at": self.clock()}, self.clock())
        except ContractError as exc:
            no_send = {**record, "submission_state": "failed", "dispatch_state": "blocked",
                       "failure_stage": "before_send", "failure": error_response(exc.code)}
            if (self._send_committed(sid, aid) and not response_observed and
                    not self.allowance.proves_no_send(no_send)):
                log_failure("successor_contract_failed_after_commit", exc)
                self._possible_send(sid)
                return
            stage = "result_validation" if response_observed else "before_send"
            self._update(sid, {"submission_state": "failed",
                                              "dispatch_state": "blocked" if stage == "before_send" else "sent",
                                              "delivery_state": "invalid" if stage == "result_validation" else "pending",
                                              "candidate_access": "unavailable_due_failure",
                                              "failure_stage": stage,
                                              "failure": error_response(exc.code)}, self.clock())
        except Exception:
            log_failure('successor_service.SuccessorService._execute.failed')
            # A durable guard commitment means the receiver may have the bytes.
            if self._send_committed(sid, aid):
                self._possible_send(sid)
            else:
                self._update(sid, {"submission_state": "failed",
                                                  "dispatch_state": "blocked", "delivery_state": "pending",
                                                  "candidate_access": "unavailable_due_failure",
                                                  "failure_stage": "before_send",
                                                  "failure": error_response("FDC_REJECTED")}, self.clock())
        finally:
            with self.authority.gate:
                self.allowance.finish(aid)

    def status(self, submission_id, trusted):
        with self.authority.gate:
            with self.store._lock:
                record = self._visible(self.store.successor_get(submission_id), trusted)
                latest = self.store.successor_latest_usage(record["attempt_id"])
        attempt = {"attempt_id": record["attempt_id"], "dispatch_state": record["dispatch_state"],
                   "delivery_state": record["delivery_state"],
                   "settlement_state": record["settlement_state"]}
        if latest:
            attempt["usage_revision"] = latest
        if record.get("failure"):
            attempt["failure"] = record["failure"]
        access = record["candidate_access"]
        result = record.get("result")
        if self._result_expired(record):
            access, result = "expired", None
        if access == "present" and result is not None:
            attempt["result"] = result
        return {"contract_version": "0.3", "handle": self._handle(record),
                "submission_state": record["submission_state"],
                "status_revision": record["status_revision"], "attempts": [attempt],
                "candidate_access": access}

    def status_by_work(self, key, trusted):
        if key["principal_id"] != trusted["principal_id"]:
            raise ContractError("NOT_FOUND_OR_FORBIDDEN", 404)
        record = self.store.successor_by_work(key)
        return self.status(self._visible(record, trusted)["submission_id"], trusted)
