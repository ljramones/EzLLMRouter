"""External accounting snapshots operations under the existing service context."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from .repositories import integration_accounting as _queries
from .store import encode
from . import integration_accounting as _api


def _expire_snapshots(self):
    # Avoid a write transaction when the indexed expiry range is empty.
    at = _api._time()
    with self.store.database.read():
        if not self.store.database.execute(_queries.EXPIRED_SNAPSHOT_EXISTS, (at,)).fetchone():
            return 0

    # Content is purged, while identity, digest and expiry evidence remain.
    def action():
        return self.store.database.execute(
            _queries.ACTION_UPDATE_INTEGRATION_SNAPSHOTS, (at,)
        ).rowcount

    return self.store.database.transaction(action)


def append_snapshot(self, principal, record):
    version = record.get("integration_version") if type(record) is dict else None
    if version not in ("2", "3"):
        raise _api.IntegrationError("UNSUPPORTED_VERSION", 426)
    record = _api._checked(record, "snapshot", version)
    dataset = self._dataset(record["dataset_id"])
    self._authorize(principal, dataset, "ingest")
    if record["status"] == "captured":
        policy = self.feature_policy
        if policy is None:
            if record["provenance"] != "synthetic" or record["classification"] != "low":
                raise _api.IntegrationError("POLICY_DENIED", 403)
            days = 397
        else:
            if (
                policy.get("mode") != "approved"
                or policy.get("approved_by") != dataset["owner_id"]
                or record["classification"] not in policy.get("max_days_by_class", {})
                or record["provenance"] == "synthetic"
            ):
                raise _api.IntegrationError("POLICY_DENIED", 403)
            days = policy["max_days_by_class"][record["classification"]]
            if type(days) is not int or not 1 <= days <= 397 or "source_expires_at" not in record:
                raise _api.IntegrationError("POLICY_DENIED", 403)
        origin = datetime.fromisoformat(record["source_at"].replace("Z", "+00:00"))
        cutoff = datetime.fromisoformat(record["retention_until"].replace("Z", "+00:00"))
        if cutoff > origin + timedelta(days=days):
            raise _api.IntegrationError("POLICY_DENIED", 403)
    did, sid = record["dataset_id"], record["snapshot_id"]
    digest = "sha256:" + hashlib.sha256(encode(record).encode()).hexdigest()
    content = {key: record[key] for key in ("features", "selected_action") if key in record}
    metadata = {key: value for key, value in record.items() if key not in content}

    def action():
        db = self.store.database
        self._authorize(principal, self._dataset(record["dataset_id"]), "ingest")
        old = db.execute(_queries.SNAPSHOT_IDENTITY, (did, sid)).fetchone()
        if old:
            if old[0] != digest:
                raise _api.IntegrationError("EVENT_CONFLICT", 409)
            return 200, {
                "integration_version": version,
                "snapshot_id": sid,
                "snapshot_digest": digest,
                "status": json.loads(old[1])["status"],
            }
        for aid, raw in db.execute(_queries.SNAPSHOT_START_REFERENCES, (did, sid)):
            attempt = json.loads(raw)
            if attempt.get("context_ref") == sid and (
                aid != record["attempt_id"] or record["snapshot_kind"] != "feature"
            ):
                raise _api.IntegrationError("EVENT_CONFLICT", 409)
        for aid, raw in db.execute(_queries.SNAPSHOT_DECISION_REFERENCES, (did, sid)):
            decision = json.loads(raw)
            if decision.get("decision_ref") == sid and (
                aid != record["attempt_id"] or record["snapshot_kind"] != "decision"
            ):
                raise _api.IntegrationError("EVENT_CONFLICT", 409)
        start = db.execute(_queries.ATTEMPT_FOR_UPDATE, (did, record["attempt_id"])).fetchone()
        if start:
            attempt = json.loads(start[0])
            expected = attempt["context_ref"] if record["snapshot_kind"] == "feature" else None
            if expected and expected != sid:
                raise _api.IntegrationError("EVENT_CONFLICT", 409)
            if (
                record["snapshot_kind"] == "decision"
                and record["available_at"] > attempt["started_at"]
            ):
                raise _api.IntegrationError("SEMANTIC_INVALID")
        if record["snapshot_kind"] == "decision" and "selected_action" in content:
            rows = db.execute(
                _queries.DECISION_EVENT_RECORD, (did, record["attempt_id"])
            ).fetchall()
            for (raw,) in rows:
                decision = json.loads(raw)
                if decision.get("decision_ref") != sid or any(
                    decision.get(key) != content["selected_action"].get(key)
                    for key in (
                        "selected_account_id",
                        "selected_model_id",
                        "policy_version",
                        "eligibility_evidence",
                    )
                    + (
                        ("operation_family", "capability", "selection_kind")
                        if version == "3"
                        else ()
                    )
                ):
                    raise _api.IntegrationError("EVENT_CONFLICT", 409)
        db.execute(
            _queries.ACTION_INSERT_INTEGRATION_SNAPSHOTS,
            (
                did,
                sid,
                record["attempt_id"],
                record["snapshot_kind"],
                digest,
                encode(metadata),
                encode(content) if content and record["retention_until"] > _api._time() else None,
            ),
        )
        return 201, {
            "integration_version": version,
            "snapshot_id": sid,
            "snapshot_digest": digest,
            "status": record["status"],
        }

    return self.store.database.transaction(action)


def snapshot(self, principal, dataset_id, snapshot_id, version="2"):
    dataset = self._dataset(dataset_id)
    self._authorize(principal, dataset, "snapshot")
    if not _api._shape(snapshot_id, _api.SCHEMA_V2["$defs"]["id"]):
        raise _api.IntegrationError("SCHEMA_INVALID")
    with self.store.database.read():
        row = self.store.database.execute(
            _queries.SNAPSHOT_SELECT_INTEGRATION_SNAPSHOTS, (dataset_id, snapshot_id)
        ).fetchone()
    if not row:
        raise _api.IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
    meta, content, digest = _api._snapshot_record(*row, _api._time())
    if (
        content
        and "sha256:" + hashlib.sha256(encode({**meta, **json.loads(content)}).encode()).hexdigest()
        != digest
    ):
        raise _api.IntegrationError("SNAPSHOT_INTEGRITY_FAILED", 503, "query_first")
    status = "expired" if meta["status"] == "captured" and content is None else meta["status"]
    return {
        **meta,
        "integration_version": version,
        "status": status,
        "snapshot_digest": digest,
        **(json.loads(content) if content else {}),
    }
