"""Coordinator status steps under the existing instance context."""

from __future__ import annotations

from datetime import datetime, timezone
from .canonical import (
    ContractError,
)
from . import core as _api


def _pending(self, record):
    try:
        current_retention = self._effective_retention(
            self._current_classification(record["classification_snapshot"])
        )
    except (ContractError, KeyError):
        current_retention = {"content_store_allowed": False}
    return {
        "contract_version": "0.2",
        "state": "pending",
        "handle": {"submission_id": record["submission_id"], "work_key": record["work_key"]},
        "pending_result_policy": "pollable_if_retained"
        if not record["wait_expired_no_store"]
        and record["content_store_allowed"]
        and current_retention["content_store_allowed"]
        else "metadata_only_no_store",
    }


def status(self, sid, trusted):
    record = self.store.get(sid)
    if (
        not record
        or record["principal_id"] != trusted["principal_id"]
        or record["task_id"] != trusted["task_id"]
    ):
        raise ContractError("NOT_FOUND_OR_FORBIDDEN", 404)
    if record["candidate_access"] == "present":
        try:
            current_retention = self._effective_retention(
                self._current_classification(record["classification_snapshot"])
            )
        except (ContractError, KeyError):
            current_retention = {"content_store_allowed": False}
        current_expiry = current_retention.get("content_expires_at")
        expired = current_expiry is not None and datetime.fromisoformat(
            current_expiry.replace("Z", "+00:00")
        ) <= datetime.now(timezone.utc)
        if (
            record["wait_expired_no_store"]
            or not record["content_store_allowed"]
            or not current_retention["content_store_allowed"]
            or expired
        ):
            self.store.update(
                sid,
                {
                    "candidate": None,
                    "candidate_access": "expired" if expired else "not_retained",
                    "updated_at": _api.now(),
                },
            )
            record = self.store.get(sid)
    attempt = {
        "attempt_id": record["attempt_id"],
        "execution_generation": record["work_key"]["execution_generation"],
        "attempt_revision": record["attempt_revision"],
        "dispatch_state": record["dispatch_state"],
        "delivery_state": record["delivery_state"],
        "cancel_state": record["cancel_state"],
        "settlement_state": record["settlement_state"],
        "generation_state": record["generation_state"],
        "usage": _api.public_usage(record["usage"]),
    }
    result = {
        "contract_version": "0.2",
        "handle": {"submission_id": sid, "work_key": record["work_key"]},
        "status_revision": record["status_revision"],
        "submission_state": record["submission_state"],
        "attempts": [attempt],
        "candidate_access": record["candidate_access"],
        "updated_at": record["updated_at"],
    }
    if record["candidate_access"] == "present" and record.get("candidate"):
        result["candidate"] = {**record["candidate"], "usage": _api.public_usage(record["usage"])}
    if record.get("terminal_failure"):
        result["terminal_failure"] = record["terminal_failure"]
        result["terminal_attempt_id"] = record["attempt_id"]
    if record.get("result_unavailable_reason"):
        result["result_unavailable_reason"] = record["result_unavailable_reason"]
    return result


def status_by_work(self, key, trusted):
    if key["principal_id"] != trusted["principal_id"]:
        raise ContractError("NOT_FOUND_OR_FORBIDDEN", 404)
    record = self.store.by_work(key)
    if not record:
        raise ContractError("NOT_FOUND_OR_FORBIDDEN", 404)
    return self.status(record["submission_id"], trusted)
