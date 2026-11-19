"""Read-only projection of an isolated, immutable Mach33 demo scope."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo


ZERO = Decimal("0.000000000")
NOTICE = "DEMO — scripted activity and simulated USD; no real provider calls"
FILTERS = {"from_date", "to_date", "person_id", "actor_id", "provider_id", "model_id", "workflow_id"}


def _money(value):
    return format(value, ".9f")


def _date(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class Mach33Demo:
    def __init__(self, scope):
        root = Path(scope)
        scope_record = json.loads((root / "scope.json").read_text())
        payload = (root / "fixture.json").read_bytes()
        if hashlib.sha256(payload).hexdigest() != scope_record["fixture_sha256"]:
            raise ValueError("demo scope content conflict")
        data = json.loads(payload)
        meta = data["metadata"]
        if (scope_record["dataset_id"] != meta["dataset_id"] or not meta["synthetic"] or
                any(not item["id"].startswith("demo.") for value in data.values() if isinstance(value, list)
                    for item in value) or any(item["credential_reference"] is not None or
                    item["endpoint"] is not None or item["inference_enabled"] for item in data["provider_accounts"])):
            raise ValueError("unsafe demo scope")
        self.data = data
        self.meta = meta
        self.maps = {key: {item["id"]: item for item in value}
                     for key, value in data.items() if isinstance(value, list)}
        self.zone = ZoneInfo(meta["display_timezone"])
        self.cutoff = _date(meta["report_cutoff_utc"])
        revisions = defaultdict(list)
        for item in data["usage_revisions"]:
            if _date(item["recorded_at"]) <= self.cutoff:
                revisions[item["attempt_id"]].append(item)
        self.revisions = {key: sorted(value, key=lambda item: (item["revision"], item["recorded_at"]))
                          for key, value in revisions.items()}
        self.rows = [self._row(item) for item in data["attempts"]]
        self.rows_by_id = {item["attempt_id"]: item for item in self.rows}

    def _label(self, section, identifier):
        if identifier == "demo.bucket.scheduled":
            return "Scheduled / system — no initiating human"
        if not identifier:
            return "Scheduled / autonomous"
        for name in (section, "users", "agents", "service_actors"):
            item = self.maps.get(name, {}).get(identifier)
            if item:
                return item.get("display_name", identifier)
        return identifier

    def _row(self, item):
        revision = self.revisions[item["id"]][-1]
        usage = revision["usage"]
        return {"dataset_id": self.meta["dataset_id"], "attempt_id": item["id"],
                "workflow_id": item["workflow_id"], "task_id": item["task_id"], "run_id": item["run_id"],
                "executing_actor_id": item["executing_actor_id"],
                "executing_actor_name": self._label("users" if item["executing_actor_type"] == "human"
                                                     else "agents", item["executing_actor_id"]),
                "initiating_user_id": item["initiating_user_id"],
                "initiating_user_name": self._label("users", item["initiating_user_id"]),
                "charging_owner_id": item["charging_owner_id"],
                "provider_id": item["provider_id"],
                "provider_name": self._label("providers", item["provider_id"]),
                "provider_account_id": item["provider_account_id"],
                "model_id": item["model_profile_id"],
                "model_name": self._label("model_profiles", item["model_profile_id"]),
                "label": item["label"], "started_at": item["started_at"], "ended_at": item["ended_at"],
                "local_date": _date(item["started_at"]).astimezone(self.zone).date().isoformat(),
                "provider_result": item["provider_result"], "retry_of_attempt_id": item["retry_of_attempt_id"],
                "simulated_provider_write": item["simulated_provider_write"],
                "usage_revision_id": revision["id"], "usage_revision": revision["revision"],
                "usage_observed_at": revision["recorded_at"], "usage_state": revision["usage_state"],
                "input_tokens": usage["input_tokens"] if usage else None,
                "output_tokens": usage["output_tokens"] if usage else None,
                "cost_state": revision["cost_state"], "currency": revision["currency"],
                "amount_decimal": revision["amount"], "price_schedule_id": revision["price_schedule_id"],
                "synthetic": True}

    @staticmethod
    def _measure(rows):
        known = [item for item in rows if item["amount_decimal"] is not None]
        return {"attempts": len(rows), "known_cost_attempts": len(known),
                "unknown_cost_attempts": len(rows) - len(known),
                "explicit_zero_attempts": sum(item["cost_state"] == "explicit_zero_demo" for item in rows),
                "unknown_usage_attempts": sum(item["input_tokens"] is None for item in rows),
                "known_cost_subtotal_usd": _money(sum((Decimal(item["amount_decimal"]) for item in known), ZERO)),
                "known_input_tokens": sum(item["input_tokens"] or 0 for item in rows),
                "known_output_tokens": sum(item["output_tokens"] or 0 for item in rows)}

    def _group(self, rows, key, section=None):
        buckets = defaultdict(list)
        for item in rows:
            buckets[item[key] or "demo.bucket.scheduled"].append(item)
        return [{"id": identifier,
                 "display_name": self._label(section, identifier) if section else identifier,
                 **self._measure(members)} for identifier, members in sorted(buckets.items())]

    def _steps(self, rows):
        allowed = {item["attempt_id"] for item in rows}
        revisions = sorted((item for aid in allowed for item in self.revisions[aid]),
                           key=lambda item: (item["recorded_at"], item["id"]))
        effective = {}
        steps = []
        for revision in revisions:
            effective[revision["attempt_id"]] = revision
            values = list(effective.values())
            steps.append({"at": revision["recorded_at"], "revision_id": revision["id"],
                          "attempt_id": revision["attempt_id"], "observed_attempts": len(effective),
                          "known_cost_subtotal_usd": _money(sum((Decimal(item["amount"])
                              for item in values if item["amount"] is not None), ZERO)),
                          "unknown_cost_attempts": sum(item["amount"] is None for item in values)})
        return steps

    def _select(self, filters):
        if set(filters) - FILTERS or any(not isinstance(value, str) for value in filters.values()):
            raise ValueError("invalid demo selector")
        for key in ("from_date", "to_date"):
            if key in filters:
                try:
                    if len(filters[key]) != 10 or datetime.strptime(filters[key], "%Y-%m-%d").strftime("%Y-%m-%d") != filters[key]:
                        raise ValueError()
                except ValueError as exc:
                    raise ValueError("invalid demo date") from exc
        if filters.get("from_date") and filters.get("to_date") and filters["from_date"] > filters["to_date"]:
            raise ValueError("invalid demo date range")
        mapping = {"person_id": "initiating_user_id", "actor_id": "executing_actor_id",
                   "provider_id": "provider_id", "model_id": "model_id", "workflow_id": "workflow_id"}
        return [item for item in self.rows if
                (not filters.get("from_date") or item["local_date"] >= filters["from_date"]) and
                (not filters.get("to_date") or item["local_date"] <= filters["to_date"]) and
                all(not filters.get(key) or item[field] == filters[key] or
                    (key == "person_id" and filters[key] == "demo.bucket.scheduled" and item[field] is None)
                    for key, field in mapping.items())]

    def report(self, filters=None):
        filters = filters or {}
        rows = self._select(filters)
        workflow_ids = {item["workflow_id"] for item in rows}
        corrected_workflow_ids = sorted({item["workflow_id"] for item in rows
            if len(self.revisions[item["attempt_id"]]) > 1})
        workflows = []
        for item in self.data["workflows"]:
            if item["id"] not in workflow_ids:
                continue
            members = [row for row in rows if row["workflow_id"] == item["id"]]
            workflows.append({"id": item["id"], "title": item["title"], "started_at": item["started_at"],
                              "local_date": _date(item["started_at"]).astimezone(self.zone).date().isoformat(),
                              "initiating_user_id": item["initiating_user_id"],
                              "initiating_user_name": self._label("users", item["initiating_user_id"]),
                              "root_run_id": item["root_run_id"], "task_outcome": item["task_outcome"],
                              **self._measure(members)})
        return {"schema": "ezllmrouter.mach33_demo_report.v1", "dataset_id": self.meta["dataset_id"],
                "display_name": self.meta["display_name"], "banner": NOTICE,
                "synthetic": True, "report_cutoff_utc": self.meta["report_cutoff_utc"],
                "display_timezone": self.meta["display_timezone"],
                "first_local_date": self.meta["first_local_date"],
                "last_local_date": self.meta["last_local_date"], "filters": filters,
                "counts": {**self._measure(rows), "workflows": len(workflows),
                           "usage_revisions": sum(len(self.revisions[item["attempt_id"]]) for item in rows),
                           "replacement_revisions": sum(len(self.revisions[item["attempt_id"]]) - 1 for item in rows),
                           "provider_results": dict(Counter(item["provider_result"] for item in rows)),
                           "workflow_outcomes": dict(Counter(item["task_outcome"] for item in workflows))},
                "by_initiating_user": self._group(rows, "initiating_user_id", "users"),
                "by_executing_actor_direct": self._group(rows, "executing_actor_id", "agents"),
                "by_provider": self._group(rows, "provider_id", "providers"),
                "by_model": self._group(rows, "model_id", "model_profiles"),
                "by_local_date": self._group(rows, "local_date"),
                "by_workflow": [{**group,
                    "title": self.maps["workflows"][group["id"]]["title"],
                    "initiating_user_id": self.maps["workflows"][group["id"]]["initiating_user_id"],
                    "task_outcome": self.maps["workflows"][group["id"]]["task_outcome"]}
                    for group in self._group(rows, "workflow_id")],
                "workflows": workflows, "corrected_workflow_ids": corrected_workflow_ids,
                "attempts": rows,
                "observation_cost_steps": self._steps(rows),
                "people": self.data["users"], "agents": self.data["agents"],
                "providers": self.data["providers"], "models": self.data["model_profiles"]}

    def workflow(self, identifier):
        item = self.maps["workflows"].get(identifier)
        if not item:
            raise KeyError(identifier)
        runs = [row for row in self.data["runs"] if row["workflow_id"] == identifier]
        tasks = [row for row in self.data["tasks"] if row["workflow_id"] == identifier]
        attempts = [row for row in self.rows if row["workflow_id"] == identifier]
        revisions = [revision for row in attempts for revision in self.revisions[row["attempt_id"]]]
        events = [row for row in self.data["timeline_events"] if row["workflow_id"] == identifier]
        outcomes = [row for row in self.data["outcomes"] if row["workflow_id"] == identifier]
        rollups = []
        by_run = {row["id"]: row for row in runs}
        for run in runs:
            descendants = {run["id"]}
            for other in runs:
                cursor = other
                while cursor.get("parent_run_id"):
                    if cursor["parent_run_id"] == run["id"]:
                        descendants.add(other["id"])
                        break
                    cursor = by_run[cursor["parent_run_id"]]
            own = [row for row in attempts if row["run_id"] == run["id"]]
            delegated = [row for row in attempts if row["run_id"] in descendants and row["run_id"] != run["id"]]
            rollups.append({"run_id": run["id"], "parent_run_id": run["parent_run_id"],
                            "actor_id": run["actor_id"], "direct": self._measure(own),
                            "delegated": self._measure(delegated), "inclusive": self._measure(own + delegated)})
        return {"schema": "ezllmrouter.mach33_demo_workflow.v1", "dataset_id": self.meta["dataset_id"],
                "banner": NOTICE, "synthetic": True, "report_cutoff_utc": self.meta["report_cutoff_utc"],
                "display_timezone": self.meta["display_timezone"], "workflow": item,
                "runs": runs, "tasks": tasks, "attempts": attempts,
                "usage_revisions": sorted(revisions, key=lambda row: (row["recorded_at"], row["id"])),
                "timeline_events": sorted(events, key=lambda row: (row["at"], row["id"])),
                "outcomes": outcomes, "run_rollups": rollups,
                "observation_cost_steps": self._steps(attempts),
                "counts": self._measure(attempts)}
