"""Prepared deterministic normal-HTTP first-owner contention harness.

The two contenders wait after the product has prepared its admission record
and immediately before its real authority gate/SQLite WorkKey transaction.
This module is inert on import. A target caller must pass the independent
same-campaign mixed allowance gate before calling run_target().
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from dev12_completion_handlers import _case_request, _census, _headers, _post
from dev12_completion_supplement_runner import _durable, _eligible, _legacy_durable


class OwnershipBarrier:
    def __init__(self, store, expected_key, trace_path=None):
        self.store = store
        self.expected_key = expected_key
        self.trace_path = trace_path
        self.lock = threading.Lock()
        self.arrivals = []
        self.owner_absent_when_both_arrived = False
        self.release_at_ns = None
        self.barrier = threading.Barrier(2, action=self._both)

    def _record(self, value):
        if self.trace_path is not None:
            from dev12_completion_runner import append_durable

            append_durable(self.trace_path, value)

    def _both(self):
        self.owner_absent_when_both_arrived = self.store.work_owner(self.expected_key) is None
        if not self.owner_absent_when_both_arrived:
            raise AssertionError("owner appeared before both reached first-write boundary")
        self.release_at_ns = time.monotonic_ns()
        self._record(
            {"kind": "ct02b_barrier_release", "at_ns": self.release_at_ns, "owner_absent": True}
        )

    def __call__(self, key, prepared):
        if key != self.expected_key or self.store.work_owner(key) is not None:
            raise AssertionError("unexpected or already owned contender WorkKey")
        plan = prepared["signed_plan"]
        identity = {
            "submission_id": prepared["submission_id"],
            "attempt_id": prepared["attempt_id"],
            "work_digest": prepared["work_digest"],
            "plan_id": plan["plan_id"],
            "signed_plan_sha256": sha256(
                json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
            ).hexdigest(),
            "signature": plan["signature"],
        }
        with self.lock:
            arrival = {
                "thread_id": threading.get_ident(),
                "at_ns": time.monotonic_ns(),
                "owner_absent": True,
                "prepared": identity,
            }
            self.arrivals.append(arrival)
            self._record({"kind": "ct02b_barrier_arrival", **arrival})
        self.barrier.wait(timeout=10)

    def checked(self):
        if (
            len(self.arrivals) != 2
            or len({item["thread_id"] for item in self.arrivals}) != 2
            or not self.owner_absent_when_both_arrived
        ):
            raise AssertionError("two pre-ownership HTTP contenders not observed")
        return {
            "arrivals": self.arrivals,
            "owner_absent_when_both_arrived": True,
            "release_at_ns": self.release_at_ns,
            "release_boundary": "before real authority gate and SQLite WorkKey transaction",
        }


def synchronized_pair(store, service, key, first, second, *, trace_path=None):
    if store.work_owner(key) is not None:
        raise AssertionError("new complete WorkKey already owned")
    if getattr(service, "_before_first_ownership", None) is not None:
        raise AssertionError("ownership instrumentation already installed")
    barrier = OwnershipBarrier(store, key, trace_path)
    service._before_first_ownership = barrier
    try:
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="dev12-first-owner") as pool:
            futures = (pool.submit(first), pool.submit(second))
            replies = [future.result(timeout=30) for future in futures]
    finally:
        del service._before_first_ownership
    return replies, barrier.checked()


def run_target(runtime, case):
    """Run only after an independent one-admission release gate has passed."""
    campaign, _counts, _states = _durable(runtime.root)
    legacy = _legacy_durable(runtime.root)
    _eligible(
        campaign,
        legacy=legacy,
        allocated_admissions=1,
        allocated_sends=1,
        allocated_usd=Decimal("0.010000000"),
    )
    request = _case_request(runtime, case)
    contender = deepcopy(request)
    contender["input"]["items"][0]["text"] = "River"
    key = {
        "principal_id": runtime.contexts_by_credential[runtime.credentials["DIRECT_DOCUMENT"]][
            "identity"
        ]["principal_id"],
        **request["work_selector"],
    }
    before = _census(runtime)
    replies, boundary = synchronized_pair(
        runtime.store,
        runtime.successor,
        key,
        lambda: _post(runtime, request, _headers(runtime)),
        lambda: _post(runtime, contender, _headers(runtime)),
    )
    after = _census(runtime)
    owner = runtime.store.work_owner(key)
    winner = next((item for item in replies if item["reply"].get("handle")), None)
    loser = next((item for item in replies if item["http_status"] == 409), None)
    if (
        owner is None
        or owner["contract_version"] != "0.3"
        or winner is None
        or loser is None
        or loser["reply"].get("code") != "WORK_CONFLICT"
        or loser["reply"].get("retry_guidance") != "never"
        or owner["submission_id"] != winner["reply"]["handle"]["submission_id"]
        or after["submissions"] != before["submissions"] + 1
        or after["campaign"]["attempt_count"] != before["campaign"]["attempt_count"] + 1
        or after["guard_ownership"] > before["guard_ownership"] + 1
        or after["receiver_arrivals"] > before["receiver_arrivals"] + 1
    ):
        raise AssertionError("synchronized target first ownership did not conserve one admission")
    return {
        "kind": "dev12_completion02_sync_http_first_owner_target_v1",
        "status": "PASS",
        "case_id": case["id"],
        "boundary": boundary,
        "raw_responses": replies,
        "owner": owner,
        "before": before,
        "after": after,
        "new_admissions": 1,
        "new_possible_sends": after["guard_ownership"] - before["guard_ownership"],
        "new_receiver_arrivals": after["receiver_arrivals"] - before["receiver_arrivals"],
    }


def preflight(root, output):
    """Record prospective one-admission allocation without releasing work."""
    if output.exists():
        raise ValueError("prospective preflight output already exists")
    campaign, counts, states = _durable(root)
    legacy = _legacy_durable(root)
    blockers = []
    if campaign["paused"]:
        blockers.append("authority_pause:" + ",".join(campaign["pause_reasons"]))
    if legacy["finite_financial_upper_bound"] is None:
        blockers.append("legacy_financial_upper_bound_unestablished")
    if datetime.now(timezone.utc) >= datetime.fromisoformat(
        campaign["expires_at"].replace("Z", "+00:00")
    ):
        blockers.append("original_24_hour_deadline_expired")
    if (
        campaign["attempt_count"] + legacy["admissions"] + 1 > 512
        or campaign["possible_send_count"] + legacy["possible_send_upper_count"] + 1 > 512
    ):
        blockers.append("mixed_count_headroom_insufficient")
    if not blockers:
        _eligible(
            campaign,
            legacy=legacy,
            allocated_admissions=1,
            allocated_sends=1,
            allocated_usd=Decimal("0.010000000"),
        )
    source = HERE / "dev12_completion_sync_first_owner.py"
    service = HERE.parents[1] / "tools/synthetic/successor_service.py"
    document = {
        "kind": "dev12_completion02_sync_http_first_owner_preflight_v1",
        "status": "BLOCKED_BY_CURRENT_AUTHORITY"
        if blockers
        else "ELIGIBLE_FOR_INDEPENDENT_RELEASE",
        "campaign_id": campaign["campaign_id"],
        "budget_account_id": campaign["budget_account_id"],
        "financial_owner_id": campaign["financial_owner_id"],
        "original_start": campaign["start_at"],
        "original_expiry": campaign["expires_at"],
        "campaign": campaign,
        "successor_counts": counts,
        "successor_states": states,
        "legacy_counts": legacy,
        "mixed_admissions": campaign["attempt_count"] + legacy["admissions"],
        "mixed_possible_send_upper_count": campaign["possible_send_count"]
        + legacy["possible_send_upper_count"],
        "prospective_allocation": {
            "new_admissions": 1,
            "new_possible_sends": 1,
            "max_reservation_usd": "0.010000000",
            "max_in_flight": 2,
        },
        "blockers": blockers,
        "no_listener_or_sender_started": True,
        "new_admissions_or_sends": 0,
        "harness_source_sha256": sha256(source.read_bytes()).hexdigest(),
        "service_source_sha256": sha256(service.read_bytes()).hexdigest(),
        "current_source_commit": subprocess.check_output(
            ("git", "rev-parse", "HEAD"), cwd=HERE.parents[1], text=True
        ).strip(),
    }
    output.write_text(json.dumps(document, sort_keys=True, indent=2) + "\n")
    return {
        "status": document["status"],
        "blockers": blockers,
        "mixed_admissions": document["mixed_admissions"],
        "mixed_possible_send_upper_count": document["mixed_possible_send_upper_count"],
    }


if __name__ == "__main__":
    print(json.dumps(preflight(Path(sys.argv[1]), Path(sys.argv[2])), sort_keys=True))
