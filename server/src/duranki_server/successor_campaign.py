"""Durable finite fictional allowance for one disposable DEV-12 campaign."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

from .store import encode
from .successor_contract import REGISTRATIONS


def _instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class FiniteSuccessorCampaign:
    def __init__(self, store, campaign_id, budget_account_id, *,
                 financial_owner_id="team.demo", wall_clock=None):
        self.store = store
        self.campaign_id = campaign_id
        self.budget_account_id = budget_account_id
        self.financial_owner_id = financial_owner_id
        self.currency = "USD"
        self.wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        store.db.executescript("""
            CREATE TABLE IF NOT EXISTS dev12_campaigns (
                campaign_id TEXT PRIMARY KEY, record TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dev12_campaign_attempts (
                attempt_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES dev12_campaigns(campaign_id),
                state TEXT NOT NULL, possible_send INTEGER NOT NULL,
                reservation_decimal TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dev12_campaign_audit (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL REFERENCES dev12_campaigns(campaign_id),
                record TEXT NOT NULL
            );
        """)

    def start(self, endpoints, owned_resources, *, max_attempts=512, max_concurrent=2,
              ceiling_decimal="10.000000000", window_hours=24):
        """Record the selected allowance before any target release."""
        instant = self.wall_clock()
        record = {"campaign_id": self.campaign_id, "budget_account_id": self.budget_account_id,
                  "financial_owner_id": self.financial_owner_id, "currency": self.currency,
                  "start_at": instant.strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "expires_at": (instant + timedelta(hours=window_hours)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "endpoints": endpoints, "owned_resources": owned_resources,
                  "max_attempts": max_attempts, "max_concurrent": max_concurrent,
                  "ceiling_decimal": ceiling_decimal, "attempt_count": 0,
                  "possible_send_count": 0, "inflight_count": 0,
                  "cumulative_reserved_decimal": "0.000000000",
                  "paused": False, "pause_reason": None, "pause_reasons": []}
        def action():
            if self.store.db.execute("SELECT 1 FROM dev12_campaigns WHERE campaign_id=?",
                                     (self.campaign_id,)).fetchone():
                raise ValueError("campaign already exists; counter reset denied")
            self.store.db.execute("INSERT INTO dev12_campaigns VALUES (?,?)",
                                  (self.campaign_id, encode(record)))
        self.store._transaction(action)
        return record

    def _record(self, db):
        row = db.execute("SELECT record FROM dev12_campaigns WHERE campaign_id=?",
                         (self.campaign_id,)).fetchone()
        if not row:
            raise PermissionError("campaign not started")
        campaign = json.loads(row[0])
        if (campaign["budget_account_id"] != self.budget_account_id or
                campaign.get("financial_owner_id", self.financial_owner_id) != self.financial_owner_id or
                campaign.get("currency", self.currency) != self.currency):
            raise PermissionError("durable campaign financial scope mismatch")
        return campaign

    def _bound_reservation(self, campaign, record):
        reservation = record["reservation"]
        if (campaign.get("financial_owner_id") is None or campaign.get("currency") != "USD" or
                reservation.get("budget_account_id") != campaign["budget_account_id"] or
                reservation.get("financial_owner_id") != campaign["financial_owner_id"] or
                reservation.get("currency") != campaign["currency"]):
            raise PermissionError("reservation outside durable campaign financial scope")

    def inspect(self):
        with self.store._lock:
            return self._record(self.store.db)

    def assert_attempt_releasable(self, record, *, committed):
        """Read the specific admitted reservation under the caller's authority gate."""
        with self.store._lock:
            campaign = self._record(self.store.db)
            self._bound_reservation(campaign, record)
            attempt = self.store.db.execute(
                "SELECT state,possible_send,reservation_decimal FROM dev12_campaign_attempts "
                "WHERE attempt_id=? AND campaign_id=?",
                (record["attempt_id"], self.campaign_id)).fetchone()
            if (not attempt or attempt[0] != "inflight" or bool(attempt[1]) != committed or
                    Decimal(attempt[2]) != Decimal(record["reservation"]["max_exposure_decimal"]) or
                    campaign["paused"] or self.wall_clock() >= _instant(campaign["expires_at"]) or
                    (not committed and campaign["possible_send_count"] >= campaign["max_attempts"])):
                raise PermissionError("attempt release scope unavailable")

    def reserve(self, db, record):
        """Called inside the same immediate transaction as successor_create."""
        campaign = self._record(db)
        self._bound_reservation(campaign, record)
        if self.wall_clock() >= _instant(campaign["expires_at"]):
            raise PermissionError("campaign release window expired")
        if (campaign["paused"] or campaign["attempt_count"] >= campaign["max_attempts"] or
                campaign["inflight_count"] >= campaign["max_concurrent"]):
            raise PermissionError("finite attempt/concurrency allowance exhausted")
        bound = Decimal(record["reservation"]["max_exposure_decimal"])
        if Decimal(campaign["cumulative_reserved_decimal"]) + bound > Decimal(campaign["ceiling_decimal"]):
            raise PermissionError("fictional campaign ceiling exhausted")
        db.execute("INSERT INTO dev12_campaign_attempts VALUES (?,?,?,?,?)",
                   (record["attempt_id"], self.campaign_id, "inflight", 0, str(bound)))
        campaign["attempt_count"] += 1
        campaign["inflight_count"] += 1
        campaign["cumulative_reserved_decimal"] = str(
            (Decimal(campaign["cumulative_reserved_decimal"]) + bound).quantize(Decimal("0.000000001")))
        db.execute("UPDATE dev12_campaigns SET record=? WHERE campaign_id=?",
                   (encode(campaign), self.campaign_id))
        record["campaign_id"] = self.campaign_id

    def mark_possible_send(self, attempt_id, *, db=None):
        def action(connection):
            campaign = self._record(connection)
            row = connection.execute(
                "SELECT state, possible_send, reservation_decimal FROM dev12_campaign_attempts WHERE attempt_id=? AND campaign_id=?",
                (attempt_id, self.campaign_id)).fetchone()
            if not row or row[1] or row[0] != "inflight":
                raise PermissionError("send ownership unavailable")
            submitted = connection.execute(
                "SELECT record FROM dev12_submissions WHERE json_extract(record,'$.attempt_id')=?",
                (attempt_id,)).fetchone()
            if not submitted:
                raise PermissionError("admitted reservation missing")
            record = json.loads(submitted[0])
            self._bound_reservation(campaign, record)
            if Decimal(row[2]) != Decimal(record["reservation"]["max_exposure_decimal"]):
                raise PermissionError("reserved bound changed")
            if (campaign["paused"] or self.wall_clock() >= _instant(campaign["expires_at"]) or
                    campaign["possible_send_count"] >= campaign["max_attempts"]):
                raise PermissionError("send release allowance exhausted")
            connection.execute("UPDATE dev12_campaign_attempts SET possible_send=1 WHERE attempt_id=?",
                               (attempt_id,))
            campaign["possible_send_count"] += 1
            connection.execute("UPDATE dev12_campaigns SET record=? WHERE campaign_id=?",
                               (encode(campaign), self.campaign_id))
        if db is not None:
            action(db)
        else:
            self.store._transaction(lambda: action(self.store.db))

    def pause_in_transaction(self, db, reason):
        """A usage/unknown transition and its scope pause share one write gate."""
        if reason not in ("unknown_outcome", "unknown_cost", "over_bound", "manual", "authority"):
            raise ValueError("unsupported campaign pause reason")
        campaign = self._record(db)
        reasons = campaign.get("pause_reasons") or ([campaign["pause_reason"]]
            if campaign.get("paused") and campaign.get("pause_reason") else [])
        if reason not in reasons:
            reasons.append(reason)
        campaign["paused"] = True
        campaign["pause_reasons"] = reasons
        campaign["pause_reason"] = reasons[0]
        db.execute("UPDATE dev12_campaigns SET record=? WHERE campaign_id=?",
                   (encode(campaign), self.campaign_id))

    @staticmethod
    def _definite_no_send(db, record):
        """Recognize a failed attempt with no guard or a trusted-guard rejection.

        A committed guard alone remains a possible send. When it exists, the
        sender's terminal observation must establish no lower transport write.
        """
        if (record.get("submission_state") != "failed" or
                record.get("failure_stage") != "before_send" or
                record.get("dispatch_state") != "blocked"):
            return False
        events = db.execute(
            "SELECT event_kind,evidence FROM dev12_evidence_events WHERE submission_id=?",
            (record["submission_id"],)).fetchall()
        kinds = {}
        for kind, raw in events:
            kinds.setdefault(kind, []).append(json.loads(raw))
        if any(kinds.get(kind) for kind in ("late_receiver_receipt_collected",
                                             "native_usage_accepted")):
            return False
        ownership = db.execute("SELECT 1 FROM dev12_send_ownership WHERE attempt_id=? "
                               "AND submission_id=?", (record["attempt_id"],
                               record["submission_id"])).fetchone()
        if ownership is None:
            return (not kinds.get("guard_committed") and
                    all(outcome.get("first_bytes_accepted") is False and
                        outcome.get("guard_committed") is False
                        for outcome in kinds.get("sender_outcome", [])))
        if (record.get("failure", {}).get("code") != "FDC_REJECTED" or
                len(kinds.get("guard_committed", [])) != 1 or
                len(kinds.get("sender_outcome", [])) != 1):
            return False
        guard = kinds["guard_committed"][0]
        outcome = kinds["sender_outcome"][0]
        return (guard.get("attempt_id") == record["attempt_id"] and
                guard.get("plan_id") == record["signed_plan"]["plan_id"] and
                outcome.get("error_type") == "GuardRejected" and
                outcome.get("guard_committed") is True and
                outcome.get("first_bytes_accepted") is False and
                outcome.get("response_received") is False)

    def resume(self, authority, *, actor_id, reason, observed_at):
        """Audit a fresh eligibility decision without changing exposure or counters."""
        if type(actor_id) is not str or not actor_id:
            raise ValueError("authenticated resume actor required")
        with authority.gate:
            def action():
                campaign = self._record(self.store.db)
                prior = {"paused": campaign["paused"], "pause_reason": campaign.get("pause_reason"),
                         "pause_reasons": campaign.get("pause_reasons") or
                           ([campaign["pause_reason"]] if campaign.get("paused") and
                             campaign.get("pause_reason") else []),
                         "attempt_count": campaign["attempt_count"],
                         "possible_send_count": campaign["possible_send_count"],
                         "inflight_count": campaign["inflight_count"],
                         "cumulative_reserved_decimal": campaign["cumulative_reserved_decimal"],
                         "expires_at": campaign["expires_at"]}
                blockers = []
                if not campaign["paused"]:
                    blockers.append("not_paused")
                if self.wall_clock() >= _instant(campaign["expires_at"]):
                    blockers.append("release_expired")
                if (campaign["attempt_count"] >= campaign["max_attempts"] or
                        campaign["possible_send_count"] >= campaign["max_attempts"] or
                        campaign["inflight_count"] >= campaign["max_concurrent"]):
                    blockers.append("allowance_exhausted")
                least_supported_reservation = min(Decimal(price["maximum_bound_decimal"])
                    for price in REGISTRATIONS["price_contracts"])
                if (Decimal(campaign["ceiling_decimal"]) -
                        Decimal(campaign["cumulative_reserved_decimal"]) < least_supported_reservation):
                    blockers.append("financial_headroom_exhausted")
                try:
                    authority.minting_snapshot()
                except PermissionError:
                    blockers.append("current_authority_denied")
                for pause in prior["pause_reasons"]:
                    if pause in ("manual", "authority", "over_bound"):
                        blockers.append("unresolved_" + pause)
                resolved = []
                no_send_reconciled = []
                for aid, raw in self.store.db.execute(
                        "SELECT a.attempt_id,s.record FROM dev12_campaign_attempts a "
                        "JOIN dev12_submissions s ON json_extract(s.record,'$.attempt_id')=a.attempt_id "
                        "WHERE a.campaign_id=?", (self.campaign_id,)).fetchall():
                    record = json.loads(raw)
                    latest = self.store.db.execute(
                        "SELECT usage FROM dev12_usage_revisions WHERE attempt_id=? "
                        "ORDER BY revision DESC LIMIT 1", (aid,)).fetchone()
                    usage = json.loads(latest[0]) if latest else None
                    if (usage is None and record.get("exposure_state") == "outstanding" and
                            self._definite_no_send(self.store.db, record)):
                        record["exposure_state"] = "not_sent"
                        record["status_revision"] += 1
                        record["updated_at"] = observed_at
                        self.store.db.execute("UPDATE dev12_submissions SET record=? WHERE submission_id=?",
                                              (encode(record), record["submission_id"]))
                        self.store.db.execute(
                            "INSERT INTO dev12_evidence_events(submission_id,event_kind,observed_at,evidence) "
                            "VALUES (?,?,?,?)", (record["submission_id"],
                            "definite_no_send_reconciled", observed_at,
                            encode({"attempt_id": aid,
                                    "basis": "qualified_sender_no_first_write"})))
                        no_send_reconciled.append(aid)
                    if ((usage is None and record.get("exposure_state") != "not_sent") or
                            (usage is not None and usage["cost_status"] in ("unknown", "over_bound")) or
                            record.get("exposure_state") in ("outstanding", "over_bound")):
                        blockers.append("unresolved_exposure:" + aid)
                    receipts = [json.loads(item[0]) for item in self.store.db.execute(
                        "SELECT evidence FROM dev12_evidence_events WHERE submission_id=? "
                        "AND event_kind='late_receiver_receipt_collected'", (record["submission_id"],))]
                    if record.get("submission_state") == "unknown" and len(receipts) != 1:
                        blockers.append("unresolved_unknown_outcome:" + aid)
                    resolved.extend(item["receipt_digest"] for item in receipts)
                decision = "refused" if blockers else "resumed"
                audit = {"kind": "campaign_resume_decision", "actor_id": actor_id,
                         "reason": reason, "observed_at": observed_at,
                         "prior_state": prior, "resolved_evidence": sorted(set(resolved)),
                         "definite_no_send_reconciled": sorted(no_send_reconciled),
                         "decision": decision, "blockers": sorted(set(blockers))}
                if not blockers:
                    campaign["paused"] = False
                    campaign["pause_reason"] = None
                    campaign["pause_reasons"] = []
                    self.store.db.execute("UPDATE dev12_campaigns SET record=? WHERE campaign_id=?",
                                          (encode(campaign), self.campaign_id))
                self.store.db.execute("INSERT INTO dev12_campaign_audit(campaign_id,record) VALUES (?,?)",
                                      (self.campaign_id, encode(audit)))
                return audit
            return self.store._transaction(action)

    def finish(self, attempt_id, *, db=None):
        """Release concurrency only; historical unknown exposure remains reserved."""
        def action(connection):
            row = connection.execute(
                "SELECT state FROM dev12_campaign_attempts WHERE attempt_id=? AND campaign_id=?",
                (attempt_id, self.campaign_id)).fetchone()
            if not row:
                raise KeyError(attempt_id)
            if row[0] == "finished":
                return
            campaign = self._record(connection)
            campaign["inflight_count"] -= 1
            connection.execute("UPDATE dev12_campaign_attempts SET state='finished' WHERE attempt_id=?",
                                  (attempt_id,))
            connection.execute("UPDATE dev12_campaigns SET record=? WHERE campaign_id=?",
                                  (encode(campaign), self.campaign_id))
        if db is not None:
            action(db)
        else:
            self.store._transaction(lambda: action(self.store.db))

    def proves_no_send(self, record):
        """Require matching campaign scope and durable evidence of no lower write."""
        if record.get("campaign_id") != self.campaign_id:
            return False
        with self.store._lock:
            return self._definite_no_send(self.store.db, record)
