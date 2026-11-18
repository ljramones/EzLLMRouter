"""Finite DEV-12 Completion 02 target runner.

Importing this module is side-effect free.  In particular, the receiver,
campaign and sender are never started by the no-send preflight.  A release
requires an exact committed inventory and an explicit ``--release`` flag.
All retained files live beneath the caller's durable artifact directory.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import tarfile
from typing import Any
import zipfile


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True) + "\n").encode("utf-8")


def append_durable(path: Path, value: dict) -> None:
    """One append-only record, flushed before the next case may execute."""
    raw = _json_bytes(value)
    with path.open("ab", buffering=0) as stream:
        if stream.write(raw) != len(raw):
            raise OSError("short case-journal write")
        os.fsync(stream.fileno())


def snapshot(path: Path) -> dict:
    """A bounded retained file reference, independent of a claimed result."""
    if not path.is_file() or path.is_symlink():
        raise AssertionError(f"evidence file absent or symlink: {path}")
    size = path.stat().st_size
    if size > 16_000_000:
        raise AssertionError(f"evidence exceeds bounded capture: {path}")
    return {"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest(),
            "bytes": size}


def _checked_artifact_root(path: str) -> Path:
    root = Path(path).resolve(strict=True)
    approved = Path("/Users/larrymitchell/Mach33/Duranki-artifacts").resolve(strict=True)
    if root == approved or approved not in root.parents or root.is_symlink():
        raise ValueError("a dedicated directory under Duranki-artifacts is required")
    if not root.is_dir() or not os.access(root, os.W_OK):
        raise ValueError("durable evidence directory unavailable")
    return root


def _tree() -> str:
    result = subprocess.run(("git", "rev-parse", "HEAD^{tree}"), cwd=ROOT,
                            capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _clean_relevant_source() -> bool:
    paths = ("server/src", "clients", "tests/gateway_integration",
             "tests/operator_console", "web", "docs/contracts/dev12-successor-01")
    changed = subprocess.run(("git", "diff", "--quiet", "HEAD", "--", *paths),
                             cwd=ROOT, check=False)
    untracked = subprocess.run(("git", "ls-files", "--others", "--exclude-standard",
                                "--", *paths), cwd=ROOT, capture_output=True,
                               text=True, check=True)
    return changed.returncode == 0 and not untracked.stdout.strip()


def preflight(plan: dict, root: Path, handlers: dict) -> dict:
    """No campaign, listener, worker request, admission or send occurs here."""
    from dev12_completion_preflight import validate
    if _tree() != plan.get("source_tree") or not _clean_relevant_source():
        return {"status": "BLOCKED_NO_SEND", "errors":
                ["committed source tree or mounted target source differs"]}
    image_ids = set()
    for artifact in plan.get("artifacts", []):
        if artifact.get("kind", "").endswith("image"):
            result = subprocess.run(("docker", "image", "inspect", artifact["path"],
                                     "--format", "{{.Id}}"), capture_output=True,
                                    text=True, check=False)
            if result.returncode == 0 and result.stdout.strip() == artifact["path"]:
                image_ids.add(artifact["path"])
    return validate(plan, handlers=handlers, artifact_root=root,
                    image_ids=image_ids)


def checked_release_receipt(plan_bytes: bytes, plan: dict, root: Path,
                            handlers: dict, *, receipt_path: Path | None = None) -> dict:
    """Verify the separate host no-send gate inside the isolated runtime.

    Docker and Git need not be present inside the service image.  The host
    gate has already checked those identities.  The runtime rechecks every
    mounted package/source byte and exact handler registration before release.
    """
    receipt_path = receipt_path or root / "preflight-receipt.json"
    if not receipt_path.is_file() or receipt_path.is_symlink():
        raise RuntimeError("host no-send preflight receipt absent")
    receipt = json.loads(receipt_path.read_bytes())
    expected = {"kind", "plan_sha256", "source_tree", "image_ids",
                "handler_identities", "artifacts", "case_count", "covered_ids",
                "covered_pairs", "max_admissions", "max_possible_sends",
                "max_exposure_decimal", "mounted_source_identity"}
    if (type(receipt) is not dict or set(receipt) != expected or
            receipt["kind"] != "dev12_completion02_no_send_preflight_v1" or
            receipt["plan_sha256"] != sha256(plan_bytes).hexdigest() or
            receipt["source_tree"] != plan["source_tree"] or
            receipt["artifacts"] != plan["artifacts"] or
            receipt["case_count"] != len(plan["cases"])):
        raise RuntimeError("host preflight receipt does not bind this exact plan")
    source_identities = receipt["handler_identities"]
    from dev12_completion_preflight import mounted_source_identity
    if mounted_source_identity() != receipt["mounted_source_identity"]:
        raise RuntimeError("mounted runtime source differs from host preflight")
    for name, identity in source_identities.items():
        registration = handlers.get(name)
        if (registration is None or
                Path(registration.source_path).name != Path(identity.get("path", "")).name or
                registration.source_sha256 != identity.get("sha256") or
                sha256(Path(registration.source_path).read_bytes()).hexdigest() !=
                    identity.get("sha256")):
            raise RuntimeError("registered handler differs from host-reviewed source")
    for artifact in receipt["artifacts"]:
        if artifact["kind"] in {"python_wheel", "js_tarball"}:
            path = Path(artifact["path"])
            if (not path.is_file() or path.is_symlink() or
                    sha256(path.read_bytes()).hexdigest() != artifact["sha256"]):
                raise RuntimeError("installed-client package differs from host preflight")
        elif artifact["path"] not in receipt["image_ids"]:
            raise RuntimeError("frozen image not in host preflight receipt")
        elif os.environ.get("DEV12_" + artifact["kind"].upper() + "_ID") != artifact["path"]:
            raise RuntimeError("running target image identity declaration differs")
    return receipt


def build_plan(*, root: Path, wheel: Path, js_package: Path,
               service_image: str, node_image: str, operator_port: int,
               campaign_id: str, budget_account_id: str,
               financial_owner_id: str) -> dict:
    """Write one exact, prospective full inventory without starting a target.

    Every selected catalog pair appears even if its handler remains missing;
    the independent no-send preflight rejects that gap.  Bounds are finite
    allocations against the owner's 512/2/USD6/24h ceiling, not observations.
    """
    from dev12_completion_catalog import REQUIRED_PAIRS, SCENARIOS
    from dev12_completion_handlers import DEV12_CASE_HANDLERS
    if not _clean_relevant_source():
        raise RuntimeError("commit reviewed target sources before freezing a plan")
    for value in (campaign_id, budget_account_id, financial_owner_id):
        if not value or len(value) > 120 or any(char.isspace() for char in value):
            raise ValueError("distinct bounded synthetic campaign/scope IDs required")
    if not 1024 <= operator_port <= 65535:
        raise ValueError("fixed operator port out of range")
    if not all(item.startswith("sha256:") and len(item) == 71
               for item in (service_image, node_image)):
        raise ValueError("exact frozen image IDs required")
    for path in (wheel, js_package):
        if not path.is_file() or path.is_symlink():
            raise ValueError("exact installed-client package absent")
    vectors = ROOT / "docs/contracts/dev12-successor-01/vectors.json"
    tariffs = ROOT / "docs/contracts/dev12-successor-01/tariffs.json"
    completion_receiver = HERE / "dev12_completion_receiver.py"
    artifacts = [
        {"kind": "python_wheel", "path": str(wheel.resolve()),
         "sha256": sha256(wheel.read_bytes()).hexdigest()},
        {"kind": "js_tarball", "path": str(js_package.resolve()),
         "sha256": sha256(js_package.read_bytes()).hexdigest()},
        {"kind": "service_image", "path": service_image,
         "sha256": service_image.removeprefix("sha256:")},
        {"kind": "node_image", "path": node_image,
         "sha256": node_image.removeprefix("sha256:")},
    ]
    source_tree = _tree()
    sends_by_scenario = {"t14_a": 2, "t24_c": 1, "t47_a": 2,
        "t48_f": 5, "t48_g": 4, "t49_d": 3,
        "t50_a": 2, "t51": 4, "t52": 2, "t53": 4,
        "t54": 2, "t55": 3, "t60": 3,
        "t45_a": 1, "t45_b": 2, "t45_c": 3,
        "t45_d": 4, "t45_e": 3,
        "t79_a": 2, "t79_b": 2}

    def limits(scenario, variant):
        if scenario == "recovery_chain":
            return 1 if variant == "unknown_pause" else 0
        if scenario in {"t03", "t50_e", "t47_b", "t47_c", "t47_d"} or scenario in {
                "t48_a", "t48_b", "t48_c", "t48_d", "t48_e",
                "t61", "t62_a", "t62_b", "t62_c", "t62_d", "t62_e",
                "t64", "t65", "t66"}:
            return 0
        if scenario == "t50_b":
            return 1
        return sends_by_scenario.get(scenario, 1)

    ordered = []
    ordered.extend(sorted(pair for pair in REQUIRED_PAIRS
        if pair[0] not in {"recovery_chain", "t50_e", "t61", "t62_a",
                           "t62_b", "t62_c", "t62_d", "t62_e",
                           "t64", "t65", "t66"}))
    ordered.extend(("recovery_chain", variant) for variant in
        ("unknown_pause", "retained_receipt", "authorized_late_append",
         "denied_resume", "eligible_resume"))
    ordered.append(("t50_e", "composed"))
    ordered.extend((scenario, "composed") for scenario in
        ("t66", "t61", "t62_a", "t62_b", "t62_c", "t62_d",
         "t62_e", "t64", "t65"))
    if len(ordered) != len(REQUIRED_PAIRS) or set(ordered) != REQUIRED_PAIRS:
        raise AssertionError("full fixed scenario inventory construction differs")

    cases = []
    chain_id = lambda variant: "case.recovery_chain." + variant
    for scenario, variant in ordered:
        variant_spec = SCENARIOS[scenario].variants[variant]
        name = "case." + scenario + "." + variant
        handler = DEV12_CASE_HANDLERS.get(variant_spec.handler)
        handler_path = (Path(handler.source_path) if handler else
                        HERE / ("dev12_completion_operator_handlers.py"
                            if variant_spec.handler in {"operator_identity",
                                "operator_reporting", "persistence_migration"}
                            else "dev12_completion_handlers.py"))
        handler_hash = sha256(handler_path.read_bytes()).hexdigest()
        sends = limits(scenario, variant)
        prerequisites = []
        late_dependencies = []
        if scenario == "recovery_chain":
            chain = ("unknown_pause", "retained_receipt", "authorized_late_append",
                     "denied_resume", "eligible_resume")
            index = chain.index(variant)
            if index:
                prerequisites.append(chain_id(chain[index - 1]))
            if variant in {"denied_resume", "eligible_resume"}:
                late_dependencies.append(chain_id("authorized_late_append"))
        if scenario == "t50_e":
            prerequisites.extend(row["id"] for row in cases
                if row["max_possible_sends"] or row["scenario_id"] == "recovery_chain")
        if scenario == "t61":
            prerequisites.extend(("case.t60.composed", chain_id("authorized_late_append")))
        if scenario == "t62_b":
            prerequisites.append(chain_id("authorized_late_append"))
        if scenario in {"t62_a", "t62_c", "t62_d", "t62_e"}:
            prerequisites.append("case.t60.composed")
        if scenario == "t64":
            prerequisites.extend("case." + item + ".composed" for item in
                ("t61", "t62_a", "t62_b", "t62_c", "t62_d", "t62_e"))
        if scenario == "t65":
            prerequisites.append("case.t64.composed")
        fixture_path = ((ROOT / "tests/development_slice/request.json") if scenario == "t03" else
                        tariffs if scenario.startswith("t48_") else
                        completion_receiver if scenario in {"t49_d", "t51",
                            "t52", "t53", "t54"} else vectors)
        expected_rejection = None
        if ((scenario == "t07_a" and variant.startswith("revoked_")) or
                (scenario == "t24_a" and variant == "queued_revocation") or
                (scenario == "t24_b" and variant == "revocation_before_write")):
            expected_rejection = {"stage": "first_write", "code": "FDC_REJECTED",
                                  "http_status": 409}
        elif scenario in {"t52", "t54"}:
            expected_rejection = {"stage": "delivery", "code": "RESULT_INVALID",
                                  "http_status": 502}
        cases.append({
            "id": name, "scenario_id": scenario, "variant": variant,
            "assurance_ids": list(SCENARIOS[scenario].assurance_ids),
            "handler": variant_spec.handler,
            "handler_source_sha256": handler_hash,
            "prerequisites": prerequisites, "late_dependencies": late_dependencies,
            "scope": campaign_id,
            "attempt_group": ("attempt-group.recovery-chain" if scenario == "recovery_chain"
                              else "attempt-group." + scenario + "." + variant),
            "installed_client_mode": ("both" if scenario.startswith("t47_") else "none"),
            "fixture": {"path": str(fixture_path),
                        "sha256": sha256(fixture_path.read_bytes()).hexdigest()},
            "source_tree": source_tree,
            "build": {"path": str(handler_path), "sha256": handler_hash},
            "max_admissions": sends, "max_possible_sends": sends,
            "max_exposure_decimal": str((Decimal("0.020000000") * sends)
                                        .quantize(Decimal("0.000000001"))),
            "expected_stages": list(variant_spec.required_stages),
            "expected_rejection": expected_rejection,
            "terminal_status": ("unknown" if
                (scenario == "recovery_chain" and variant == "unknown_pause") or
                (scenario == "t24_b" and variant == "partial_write") or
                scenario in {"t24_c", "t50_c"} else
                "failed" if (scenario == "t07_a" and variant.startswith("revoked_")) or
                (scenario == "t24_a" and variant == "queued_revocation") or
                (scenario == "t24_b" and variant == "revocation_before_write") or
                scenario in {"t52", "t54"} else "completed"),
            "evidence_paths": ["cases/" + name + ".json"],
            "predicates": list(variant_spec.assertion_ids),
            "evidence_kind": "new", "reuse_identity": None,
            "phase": variant_spec.phase,
        })
    envelope = {"campaign_id": campaign_id,
        "budget_account_id": budget_account_id,
        "financial_owner_id": financial_owner_id,
        "currency": "USD", "max_admissions": 512,
        "max_possible_sends": 512, "max_inflight": 2,
        "ceiling_decimal": "6.000000000", "window_hours": 24,
        "real_provider_calls": 0, "operator_port": operator_port,
        "service_network_mode": "bridge",
        "rerun_headroom_admissions": 64,
        "rerun_headroom_sends": 64,
        "rerun_headroom_decimal": "1.000000000",
        "preexisting_exposure_decimal": "0.000000000"}
    return {"envelope": envelope, "cases": cases,
            "artifacts": artifacts, "source_tree": source_tree}


def _journal_rows(path: Path) -> list[dict]:
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("existing append-only campaign journal absent")
    rows = []
    for number, line in enumerate(path.read_bytes().splitlines(), 1):
        try:
            row = json.loads(line)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"campaign journal row {number} invalid") from exc
        if type(row) is not dict:
            raise RuntimeError(f"campaign journal row {number} invalid")
        rows.append(row)
    return rows


def continuation_checkpoint(root: Path, prior_plan: dict,
                            prior_plan_bytes: bytes) -> dict:
    """Prove which exact original cases passed before a stopped campaign.

    A pass is accepted only with its retained evidence and independent durable
    correlation result.  No case result is inferred from its position alone.
    """
    from dev12_completion_preflight import verify_case_result
    prior_receipt_path = root / "preflight-receipt.json"
    if not prior_receipt_path.is_file() or prior_receipt_path.is_symlink():
        raise RuntimeError("original host preflight receipt absent")
    prior_receipt = json.loads(prior_receipt_path.read_bytes())
    if (prior_receipt.get("plan_sha256") != sha256(prior_plan_bytes).hexdigest() or
            prior_receipt.get("source_tree") != prior_plan["source_tree"] or
            prior_receipt.get("case_count") != len(prior_plan["cases"])):
        raise RuntimeError("original exact preflight receipt differs from plan bytes")
    journal = _journal_rows(root / "case-journal.jsonl")
    started = [row for row in journal if row.get("kind") == "campaign_started"]
    if len(started) != 1:
        raise RuntimeError("continuation requires exactly one original campaign start")
    identity = started[0].get("identity", {})
    if (identity.get("plan_sha256") != sha256(_json_bytes(prior_plan)).hexdigest() or
            identity.get("campaign_id") != prior_plan["envelope"]["campaign_id"]):
        raise RuntimeError("original journal does not bind original plan/campaign")
    # The on-disk plan has pretty JSON while the original release identity used
    # the canonical compact representation. Both are retained and checked.
    releases = _journal_rows(root / "release-identity.jsonl")
    if (not releases or releases[0].get("plan_sha256") != identity["plan_sha256"] or
            releases[0].get("source_tree") != prior_plan["source_tree"]):
        raise RuntimeError("original release identity absent or changed")
    by_id = {case["id"]: case for case in prior_plan["cases"]}
    ended = [row for row in journal if row.get("kind") == "case_end"]
    if not ended or len({row.get("case_id") for row in ended}) != len(ended):
        raise RuntimeError("original case ends absent or repeated")
    passed = []
    failed = None
    for index, row in enumerate(ended[:11]):
        case = prior_plan["cases"][index]
        if row.get("case_id") != case["id"] or row.get("scenario_id") != case["scenario_id"] or \
                row.get("variant") != case["variant"]:
            raise RuntimeError("original case journal differs from ordered inventory")
        if row.get("status") == "PASS" and failed is None:
            verified = verify_case_result(case, row.get("result"), root,
                actual=row.get("actual_correlation"), require_actual=True)
            if verified["status"] != "PASS" or row.get("verification", {}).get("status") != "PASS":
                raise RuntimeError("historical PASS lacks intact source-bound evidence")
            passed.append(case["id"])
        elif row.get("status") == "FAIL" and failed is None and index == 10:
            failed = row
        else:
            raise RuntimeError("continuation cannot skip a nonterminal or later failed case")
    if failed is None or (failed["scenario_id"], failed["variant"]) != \
            ("t24_b", "partial_write"):
        raise RuntimeError("only the observed partial-write stop is supported")
    failed_case = by_id[failed["case_id"]]
    evidence = root / failed_case["evidence_paths"][0]
    if not evidence.is_file() or evidence.is_symlink():
        raise RuntimeError("original failed case evidence absent")
    original = json.loads(evidence.read_bytes())
    attempt_id = original.get("actual_attempt_id")
    payload = original.get("payload", {})
    if (not isinstance(attempt_id, str) or
            payload.get("late", {}).get("collection") != "accepted" or
            payload.get("late", {}).get("resume", {}).get("decision") != "refused" or
            payload.get("late", {}).get("status", {}).get("attempts", [{}])[0].get(
                "usage_revision", {}).get("cost_status") != "calculated"):
        raise RuntimeError("original partial-write evidence is not the reviewed stop")
    continuation_number = 1
    latest_failed = failed
    latest_evidence = snapshot(evidence)
    if len(ended) >= 12:
        continuation_number = 2
        cont1_plan_path = root / "plan.continuation1.json"
        cont1_receipt_path = root / "preflight-receipt-continuation1.json"
        if any(not path.is_file() or path.is_symlink()
               for path in (cont1_plan_path, cont1_receipt_path)):
            raise RuntimeError("first continuation plan/receipt absent")
        cont1_raw = cont1_plan_path.read_bytes()
        cont1_plan = json.loads(cont1_raw)
        cont1_receipt = json.loads(cont1_receipt_path.read_bytes())
        cont1_case = cont1_plan["cases"][10]
        cont1_end = ended[11]
        cont1_gates = [row for row in _journal_rows(root / "release-gate.jsonl")
                       if row.get("plan_sha256") == sha256(cont1_raw).hexdigest()]
        cont1_releases = [row for row in releases
                          if row.get("kind") == "continuation_released" and
                             row.get("plan_sha256") == sha256(cont1_raw).hexdigest()]
        if (cont1_receipt.get("plan_sha256") != sha256(cont1_raw).hexdigest() or
                cont1_receipt.get("source_tree") != cont1_plan["source_tree"] or
                len(cont1_gates) != 1 or
                cont1_gates[0].get("preflight_receipt_sha256") !=
                    sha256(cont1_receipt_path.read_bytes()).hexdigest() or
                len(cont1_releases) != 1 or
                cont1_releases[0].get("plan_sha256") != cont1_receipt["plan_sha256"] or
                cont1_releases[0].get("mounted_source") !=
                    cont1_receipt.get("mounted_source_identity") or
                cont1_releases[0].get("campaign_id") != identity["campaign_id"] or
                cont1_releases[0].get("original_start_at") !=
                    started[0]["allowance"]["start_at"] or
                cont1_case["id"] != failed["case_id"] + ".continuation1" or
                (cont1_case["max_admissions"], cont1_case["max_possible_sends"],
                 cont1_case["max_exposure_decimal"]) != (0, 0, "0.000000000") or
                cont1_end.get("case_id") != cont1_case["id"] or
                cont1_end.get("status") != "FAIL" or
                (cont1_end.get("scenario_id"), cont1_end.get("variant")) !=
                    ("t24_b", "partial_write")):
            raise RuntimeError("first continuation identity/result differs")
        cont1_evidence = root / cont1_case["evidence_paths"][0]
        if not cont1_evidence.is_file() or cont1_evidence.is_symlink():
            raise RuntimeError("first continuation failed evidence absent")
        cont1 = json.loads(cont1_evidence.read_bytes())
        cont1_payload = cont1.get("payload", {})
        before, after = (cont1_payload.get("campaign_before", {}),
                         cont1_payload.get("campaign_after", {}))
        original_blockers = {item.removeprefix("unresolved_exposure:")
            for item in payload["late"]["resume"].get("blockers", [])
            if item.startswith("unresolved_exposure:")}
        if (cont1.get("actual_attempt_id") != attempt_id or
                cont1.get("checks", {}).get("t24_b.partial_write", {}).get("passed") is not False or
                cont1_payload.get("continuation_of_case_id") != failed["case_id"] or
                cont1_payload.get("new_resume_audit", {}).get("decision") != "resumed" or
                len(original_blockers) != 3 or
                set(cont1_payload.get("new_resume_audit", {}).get(
                    "definite_no_send_reconciled", [])) != original_blockers or
                cont1_payload.get("new_admissions") != 0 or
                cont1_payload.get("new_possible_sends") != 0 or
                any(before.get(key) != after.get(key) for key in (
                    "start_at", "expires_at", "attempt_count", "possible_send_count",
                    "cumulative_reserved_decimal")) or
                before.get("paused") is not True or after.get("paused") is not False or
                cont1_payload.get("receiver_arrivals_before") != 8 or
                cont1_payload.get("receiver_arrivals_after") != 8 or
                any(cont1_end["campaign_after"].get(key) != after.get(key)
                    for key in ("attempt_count", "possible_send_count",
                                "cumulative_reserved_decimal", "paused"))):
            raise RuntimeError("first continuation no-send resume evidence differs")
        latest_failed = cont1_end
        latest_evidence = snapshot(cont1_evidence)
    elif len(ended) != 11:
        raise RuntimeError("unsupported stopped continuation chain length")
    failed_id = failed["case_id"]
    latest_plan_path = root / "plan.json"
    failed_attempt_ids = [attempt_id]
    retained_t47_live_attempt_ids = []
    retained_t47_live_evidence = None
    retained_t60_positive_attempt_ids = []
    if len(ended) > 12:
        continuation_number = 3
        cont2_plan_path = root / "plan.continuation2.json"
        cont2_receipt_path = root / "preflight-receipt-continuation2.json"
        if any(not path.is_file() or path.is_symlink()
               for path in (cont2_plan_path, cont2_receipt_path)):
            raise RuntimeError("second continuation plan/receipt absent")
        cont2_raw = cont2_plan_path.read_bytes()
        cont2_plan = json.loads(cont2_raw)
        cont2_receipt = json.loads(cont2_receipt_path.read_bytes())
        cont2_gates = [row for row in _journal_rows(root / "release-gate.jsonl")
                       if row.get("plan_sha256") == sha256(cont2_raw).hexdigest()]
        cont2_releases = [row for row in releases
            if row.get("kind") == "continuation_released" and
               row.get("plan_sha256") == sha256(cont2_raw).hexdigest()]
        if (cont2_receipt.get("plan_sha256") != sha256(cont2_raw).hexdigest() or
                cont2_receipt.get("source_tree") != cont2_plan["source_tree"] or
                len(cont2_gates) != 1 or
                cont2_gates[0].get("preflight_receipt_sha256") !=
                    sha256(cont2_receipt_path.read_bytes()).hexdigest() or
                len(cont2_releases) != 1 or
                cont2_releases[0].get("mounted_source") !=
                    cont2_receipt.get("mounted_source_identity") or
                cont2_releases[0].get("original_start_at") !=
                    started[0]["allowance"]["start_at"]):
            raise RuntimeError("second continuation source/release identity differs")
        if len(ended) < 14:
            raise RuntimeError("second continuation lacks repaired case and next stop")
        for index, row in enumerate(ended[12:27], 10):
            case = cont2_plan["cases"][index]
            if (row.get("case_id") != case["id"] or
                    row.get("scenario_id") != case["scenario_id"] or
                    row.get("variant") != case["variant"] or
                    row.get("status") != "PASS"):
                raise RuntimeError("second continuation completed case order differs")
            verified = verify_case_result(case, row.get("result"), root,
                actual=row.get("actual_correlation"), require_actual=True)
            if verified["status"] != "PASS" or row.get("verification", {}).get("status") != "PASS":
                raise RuntimeError("second continuation PASS evidence changed")
            passed.append(case["id"])
        latest_failed = ended[27]
        failed_case = cont2_plan["cases"][len(passed)]
        if (latest_failed.get("case_id") != failed_case["id"] or
                latest_failed.get("status") != "FAIL" or
                (latest_failed.get("scenario_id"), latest_failed.get("variant")) !=
                    ("t47_a", "composed")):
            raise RuntimeError("only the observed installed-client T47a stop is supported")
        failed_id = failed_case["id"]
        t47_path = root / failed_case["evidence_paths"][0]
        if not t47_path.is_file() or t47_path.is_symlink():
            raise RuntimeError("installed-client failed evidence absent")
        t47 = json.loads(t47_path.read_bytes())
        live = t47.get("payload", {}).get("live_target", {})
        python_reply = live.get("python_reply", {})
        python_status = live.get("python_status", {})
        js = live.get("commonjs_observed", {})
        js_reply, js_status = js.get("reply", {}), js.get("status", {})
        python_aid, js_aid = python_reply.get("attempt_id"), js_reply.get("attempt_id")
        before, after = live.get("before", {}), live.get("after", {})
        if (t47.get("actual_attempt_id") != failed_case["attempt_group"] or
                set(t47.get("checks", {})) != set(failed_case["predicates"]) or
                any(value.get("passed") is not True for value in t47["checks"].values()) or
                not python_aid or not js_aid or python_aid == js_aid or
                python_status.get("submission_state") != "completed" or
                js_status.get("submission_state") != "completed" or
                python_status.get("attempts", [{}])[0].get("attempt_id") != python_aid or
                js_status.get("attempts", [{}])[0].get("attempt_id") != js_aid or
                before.get("campaign", {}).get("attempt_count") != 33 or
                after.get("campaign", {}).get("attempt_count") != 35 or
                before.get("campaign", {}).get("possible_send_count") != 33 or
                after.get("campaign", {}).get("possible_send_count") != 35 or
                before.get("receiver_arrivals") != 22 or
                after.get("receiver_arrivals") != 24 or
                after.get("campaign", {}).get("cumulative_reserved_decimal") !=
                    "0.008000003" or
                latest_failed["campaign_after"] != after["campaign"]):
            raise RuntimeError("installed-client failure is not the retained two-send case")
        failed_attempt_ids = [python_aid, js_aid]
        retained_t47_live_attempt_ids = [python_aid, js_aid]
        retained_t47_live_evidence = snapshot(t47_path)
        latest_evidence = snapshot(t47_path)
        latest_plan_path = cont2_plan_path
    if len(ended) > 28:
        continuation_number = 4
        cont3_plan_path = root / "plan.continuation3.json"
        cont3_receipt_path = root / "preflight-receipt-continuation3.json"
        if any(not path.is_file() or path.is_symlink()
               for path in (cont3_plan_path, cont3_receipt_path)):
            raise RuntimeError("third continuation plan/receipt absent")
        cont3_raw = cont3_plan_path.read_bytes()
        cont3_plan = json.loads(cont3_raw)
        cont3_receipt = json.loads(cont3_receipt_path.read_bytes())
        cont3_gates = [row for row in _journal_rows(root / "release-gate.jsonl")
                       if row.get("plan_sha256") == sha256(cont3_raw).hexdigest()]
        cont3_releases = [row for row in releases
            if row.get("kind") == "continuation_released" and
               row.get("plan_sha256") == sha256(cont3_raw).hexdigest()]
        if (cont3_receipt.get("plan_sha256") != sha256(cont3_raw).hexdigest() or
                cont3_receipt.get("source_tree") != cont3_plan["source_tree"] or
                len(cont3_gates) != 1 or
                cont3_gates[0].get("preflight_receipt_sha256") !=
                    sha256(cont3_receipt_path.read_bytes()).hexdigest() or
                len(cont3_releases) != 1 or
                cont3_releases[0].get("mounted_source") !=
                    cont3_receipt.get("mounted_source_identity") or
                cont3_releases[0].get("original_start_at") !=
                    started[0]["allowance"]["start_at"]):
            raise RuntimeError("third continuation source/release identity differs")
        if len(ended) < 30:
            raise RuntimeError("third continuation lacks repaired case and next stop")
        for index, row in enumerate(ended[28:43], 25):
            case = cont3_plan["cases"][index]
            if (row.get("case_id") != case["id"] or
                    row.get("scenario_id") != case["scenario_id"] or
                    row.get("variant") != case["variant"] or
                    row.get("status") != "PASS"):
                raise RuntimeError("third continuation completed case order differs")
            verified = verify_case_result(case, row.get("result"), root,
                actual=row.get("actual_correlation"), require_actual=True)
            if verified["status"] != "PASS" or row.get("verification", {}).get("status") != "PASS":
                raise RuntimeError("third continuation PASS evidence changed")
            passed.append(case["id"])
        latest_failed = ended[43]
        failed_case = cont3_plan["cases"][len(passed)]
        if (latest_failed.get("case_id") != failed_case["id"] or
                latest_failed.get("status") != "FAIL" or
                (latest_failed.get("scenario_id"), latest_failed.get("variant")) !=
                    ("t49_d", "composed")):
            raise RuntimeError("only the observed native-evidence T49d stop is supported")
        t49_path = root / failed_case["evidence_paths"][0]
        if not t49_path.is_file() or t49_path.is_symlink():
            raise RuntimeError("native-evidence failed case absent")
        t49 = json.loads(t49_path.read_bytes())
        observations = t49.get("payload", {}).get("observations", [])
        if len(observations) != 3:
            raise RuntimeError("native-evidence case did not retain three observations")
        aids = [item.get("reply", {}).get("reply", {}).get("attempt_id")
                for item in observations]
        out_domain = observations[1].get("status_before", {}).get("attempts", [{}])[0].get(
            "usage_revision", {})
        if (len(set(aids)) != 3 or any(not aid for aid in aids) or
                t49.get("actual_attempt_id") != aids[0] or
                t49.get("checks", {}).get("t49_d.out_of_domain", {}).get("passed") is not False or
                out_domain.get("revision") != 1 or
                out_domain.get("cost_status") != "unknown" or
                "amount_decimal" in out_domain or
                out_domain.get("components", [{}])[0].get("presence") != "known" or
                out_domain.get("components", [{}])[0].get("quantity") != 999999999 or
                any(item.get("status_after", {}).get("attempts", [{}])[0].get(
                    "usage_revision", {}).get("revision") != 2 or
                    item.get("status_after", {}).get("attempts", [{}])[0].get(
                    "usage_revision", {}).get("cost_status") != "calculated"
                    for item in observations) or
                latest_failed["campaign_after"]["attempt_count"] != 51 or
                latest_failed["campaign_after"]["possible_send_count"] != 51 or
                latest_failed["campaign_after"]["cumulative_reserved_decimal"] !=
                    "0.012200008" or latest_failed["campaign_after"]["paused"]):
            raise RuntimeError("native-evidence failure differs from retained observations")
        failed_id = failed_case["id"]
        failed_attempt_ids = aids
        latest_evidence = snapshot(t49_path)
        latest_plan_path = cont3_plan_path
    if len(ended) > 44:
        import sqlite3
        continuation_number = 5
        cont4_plan_path = root / "plan.continuation4.json"
        cont4_receipt_path = root / "preflight-receipt-continuation4.json"
        if any(not path.is_file() or path.is_symlink()
               for path in (cont4_plan_path, cont4_receipt_path)):
            raise RuntimeError("fourth continuation plan/receipt absent")
        cont4_raw = cont4_plan_path.read_bytes()
        cont4_plan = json.loads(cont4_raw)
        cont4_receipt = json.loads(cont4_receipt_path.read_bytes())
        cont4_gates = [row for row in _journal_rows(root / "release-gate.jsonl")
                       if row.get("plan_sha256") == sha256(cont4_raw).hexdigest()]
        cont4_releases = [row for row in releases
            if row.get("kind") == "continuation_released" and
               row.get("plan_sha256") == sha256(cont4_raw).hexdigest()]
        if (cont4_receipt.get("plan_sha256") != sha256(cont4_raw).hexdigest() or
                cont4_receipt.get("source_tree") != cont4_plan["source_tree"] or
                len(cont4_gates) != 1 or
                cont4_gates[0].get("preflight_receipt_sha256") !=
                    sha256(cont4_receipt_path.read_bytes()).hexdigest() or
                len(cont4_releases) != 1 or
                cont4_releases[0].get("mounted_source") !=
                    cont4_receipt.get("mounted_source_identity") or
                cont4_releases[0].get("original_start_at") !=
                    started[0]["allowance"]["start_at"]):
            raise RuntimeError("fourth continuation source/release identity differs")
        if len(ended) < 46:
            raise RuntimeError("fourth continuation lacks repaired case and next stop")
        for index, row in enumerate(ended[44:56], 40):
            case = cont4_plan["cases"][index]
            if (row.get("case_id") != case["id"] or
                    row.get("scenario_id") != case["scenario_id"] or
                    row.get("variant") != case["variant"] or
                    row.get("status") != "PASS"):
                raise RuntimeError("fourth continuation completed case order differs")
            verified = verify_case_result(case, row.get("result"), root,
                actual=row.get("actual_correlation"), require_actual=True)
            if verified["status"] != "PASS" or row.get("verification", {}).get("status") != "PASS":
                raise RuntimeError("fourth continuation PASS evidence changed")
            passed.append(case["id"])
        latest_failed = ended[56]
        failed_case = cont4_plan["cases"][len(passed)]
        if (latest_failed.get("case_id") != failed_case["id"] or
                latest_failed.get("status") != "FAIL" or
                (latest_failed.get("scenario_id"), latest_failed.get("variant")) !=
                    ("t60", "composed") or
                (root / failed_case["evidence_paths"][0]).exists()):
            raise RuntimeError("only the observed pre-reporting T60 stop is supported")
        with sqlite3.connect(f"file:{root / 'campaign.sqlite'}?immutable=1", uri=True) as db:
            positives = [json.loads(row[0]) for row in db.execute(
                "SELECT record FROM dev12_submissions WHERE "
                "json_extract(record,'$.work_key.step_id')=?",
                ("step.completion02.t60.composed",))]
            guarded = {row[0]: row[1] for row in db.execute(
                "SELECT attempt_id,submission_id FROM dev12_send_ownership")}
            usage = {row[0] for row in db.execute(
                "SELECT DISTINCT attempt_id FROM dev12_usage_revisions")}
        receivers = [json.loads(line) for line in
                     (root / "receiver.jsonl").read_bytes().splitlines()]
        by_principal = {row["work_key"]["principal_id"]: row for row in positives}
        if (len(positives) != 3 or set(by_principal) !=
                {"user.demo", "svc.vega", "svc.orion"} or
                len({row["attempt_id"] for row in positives}) != 3 or
                any(row["submission_state"] != "completed" or
                    row["settlement_state"] != "calculated" or
                    row["campaign_id"] != prior_plan["envelope"]["campaign_id"] or
                    guarded.get(row["attempt_id"]) != row["submission_id"] or
                    row["attempt_id"] not in usage or
                    sum(item.get("attempt_id") == row["attempt_id"] for item in receivers) != 1
                    for row in positives) or
                by_principal["user.demo"]["trusted_identity"]["actor_id"] != "user.demo" or
                by_principal["svc.vega"]["trusted_identity"]["actor_id"] != "agent.vega" or
                by_principal["svc.orion"]["trusted_identity"]["actor_id"] != "svc.orion" or
                by_principal["svc.vega"]["request"]["metadata"]["initiating_user_id"] !=
                    "user.demo" or
                by_principal["svc.orion"]["request"]["metadata"].get(
                    "initiating_user_id") is not None or
                latest_failed["campaign_after"]["attempt_count"] != 76 or
                latest_failed["campaign_after"]["possible_send_count"] != 76 or
                latest_failed["campaign_after"]["cumulative_reserved_decimal"] !=
                    "0.020400018" or latest_failed["campaign_after"]["paused"] or
                latest_failed["receiver_arrivals_after"] != 65 or len(receivers) < 65 or
                "Cannot open a client instance more than once" not in
                    latest_failed.get("error", "")):
            raise RuntimeError("T60 stopped after a different send/reporting boundary")
        retained_t60_positive_attempt_ids = [by_principal[key]["attempt_id"] for key in
            ("user.demo", "svc.vega", "svc.orion")]
        failed_id = failed_case["id"]
        failed_attempt_ids = retained_t60_positive_attempt_ids
        latest_evidence = None
        latest_plan_path = cont4_plan_path
    if len(ended) > 57:
        continuation_number = 6
        cont5_plan_path = root / "plan.continuation5.json"
        cont5_receipt_path = root / "preflight-receipt-continuation5.json"
        if any(not path.is_file() or path.is_symlink()
               for path in (cont5_plan_path, cont5_receipt_path)):
            raise RuntimeError("fifth continuation plan/receipt absent")
        cont5_raw = cont5_plan_path.read_bytes()
        cont5_plan = json.loads(cont5_raw)
        cont5_receipt = json.loads(cont5_receipt_path.read_bytes())
        cont5_gates = [row for row in _journal_rows(root / "release-gate.jsonl")
                       if row.get("plan_sha256") == sha256(cont5_raw).hexdigest()]
        cont5_releases = [row for row in releases
            if row.get("kind") == "continuation_released" and
               row.get("plan_sha256") == sha256(cont5_raw).hexdigest()]
        if (cont5_receipt.get("plan_sha256") != sha256(cont5_raw).hexdigest() or
                cont5_receipt.get("source_tree") != cont5_plan["source_tree"] or
                len(cont5_gates) != 1 or
                cont5_gates[0].get("preflight_receipt_sha256") !=
                    sha256(cont5_receipt_path.read_bytes()).hexdigest() or
                len(cont5_releases) != 1 or
                cont5_releases[0].get("mounted_source") !=
                    cont5_receipt.get("mounted_source_identity") or
                cont5_releases[0].get("original_start_at") !=
                    started[0]["allowance"]["start_at"]):
            raise RuntimeError("fifth continuation source/release identity differs")
        if len(ended) < 59:
            raise RuntimeError("fifth continuation lacks repaired case and next stop")
        for index, row in enumerate(ended[57:79], 52):
            case = cont5_plan["cases"][index]
            if (row.get("case_id") != case["id"] or
                    row.get("scenario_id") != case["scenario_id"] or
                    row.get("variant") != case["variant"] or
                    row.get("status") != "PASS"):
                raise RuntimeError("fifth continuation completed case order differs")
            verified = verify_case_result(case, row.get("result"), root,
                actual=row.get("actual_correlation"), require_actual=True)
            if verified["status"] != "PASS" or row.get("verification", {}).get("status") != "PASS":
                raise RuntimeError("fifth continuation PASS evidence changed")
            passed.append(case["id"])
        latest_failed = ended[79]
        failed_case = cont5_plan["cases"][len(passed)]
        latest_begins = [row for row in journal if row.get("kind") == "case_begin" and
                         row.get("case_id") == failed_case["id"]]
        if (len(latest_begins) != 1 or
                latest_failed.get("case_id") != failed_case["id"] or
                latest_failed.get("status") != "FAIL" or
                (latest_failed.get("scenario_id"), latest_failed.get("variant")) !=
                    ("t62_b", "composed") or
                (root / failed_case["evidence_paths"][0]).exists() or
                "two accepted revisions at distinct UTC seconds required" not in
                    latest_failed.get("error", "") or
                latest_begins[0].get("campaign_before") !=
                    latest_failed.get("campaign_after") or
                latest_begins[0].get("receiver_arrivals_before") !=
                    latest_failed.get("receiver_arrivals_after") or
                latest_failed["campaign_after"]["attempt_count"] != 91 or
                latest_failed["campaign_after"]["possible_send_count"] != 91 or
                latest_failed["campaign_after"]["cumulative_reserved_decimal"] !=
                    "0.027600030" or latest_failed["campaign_after"]["paused"]):
            raise RuntimeError("T62b stopped after a different admission/send boundary")
        failed_id = failed_case["id"]
        failed_attempt_ids = []
        latest_evidence = None
        latest_plan_path = cont5_plan_path
    if len(ended) > 80:
        continuation_number = 7
        cont6_plan_path = root / "plan.continuation6.json"
        cont6_receipt_path = root / "preflight-receipt-continuation6.json"
        if any(not path.is_file() or path.is_symlink()
               for path in (cont6_plan_path, cont6_receipt_path)):
            raise RuntimeError("sixth continuation plan/receipt absent")
        cont6_raw = cont6_plan_path.read_bytes()
        cont6_plan = json.loads(cont6_raw)
        cont6_receipt = json.loads(cont6_receipt_path.read_bytes())
        cont6_gates = [row for row in _journal_rows(root / "release-gate.jsonl")
                       if row.get("plan_sha256") == sha256(cont6_raw).hexdigest()]
        cont6_releases = [row for row in releases
            if row.get("kind") == "continuation_released" and
               row.get("plan_sha256") == sha256(cont6_raw).hexdigest()]
        if (cont6_receipt.get("plan_sha256") != sha256(cont6_raw).hexdigest() or
                cont6_receipt.get("source_tree") != cont6_plan["source_tree"] or
                len(cont6_gates) != 1 or
                cont6_gates[0].get("preflight_receipt_sha256") !=
                    sha256(cont6_receipt_path.read_bytes()).hexdigest() or
                len(cont6_releases) != 1 or
                cont6_releases[0].get("mounted_source") !=
                    cont6_receipt.get("mounted_source_identity") or
                cont6_releases[0].get("original_start_at") !=
                    started[0]["allowance"]["start_at"]):
            raise RuntimeError("sixth continuation source/release identity differs")
        if len(ended) < 83:
            raise RuntimeError("sixth continuation has a different completed-case count")
        for index, row in enumerate(ended[80:83], 74):
            case = cont6_plan["cases"][index]
            if (row.get("case_id") != case["id"] or
                    row.get("scenario_id") != case["scenario_id"] or
                    row.get("variant") != case["variant"] or
                    row.get("status") != "PASS"):
                raise RuntimeError("sixth continuation completed case order differs")
            verified = verify_case_result(case, row.get("result"), root,
                actual=row.get("actual_correlation"), require_actual=True)
            if verified["status"] != "PASS" or row.get("verification", {}).get("status") != "PASS":
                raise RuntimeError("sixth continuation PASS evidence changed")
            passed.append(case["id"])
        unstarted = cont6_plan["cases"][len(passed)]
        if (len(passed) != 77 or
                (unstarted["scenario_id"], unstarted["variant"]) != ("t62_e", "composed") or
                unstarted["id"] != "case.t62_e.composed" or
                (len(ended) == 83 and any(row.get("kind") in {"case_begin", "case_end"} and
                    row.get("case_id") == unstarted["id"] for row in journal)) or
                (len(ended) == 83 and (root / unstarted["evidence_paths"][0]).exists()) or
                ended[82]["campaign_after"]["attempt_count"] != 91 or
                ended[82]["campaign_after"]["possible_send_count"] != 91 or
                ended[82]["campaign_after"]["cumulative_reserved_decimal"] !=
                    "0.027600030" or ended[82]["campaign_after"]["paused"] or
                ended[82]["receiver_arrivals_after"] != 80 or
                len(_journal_rows(root / "receiver.jsonl")) != 80):
            raise RuntimeError("T62e did not stop before case begin with unchanged exposure")
        failed_id = unstarted["id"]
        latest_failed = {"case_id": failed_id,
                         "campaign_after": ended[82]["campaign_after"]}
        failed_attempt_ids = []
        latest_evidence = None
        latest_plan_path = cont6_plan_path
    if len(ended) > 83:
        continuation_number = 8
        cont7_plan_path = root / "plan.continuation7.json"
        cont7_receipt_path = root / "preflight-receipt-continuation7.json"
        if any(not path.is_file() or path.is_symlink()
               for path in (cont7_plan_path, cont7_receipt_path)):
            raise RuntimeError("seventh continuation plan/receipt absent")
        cont7_raw = cont7_plan_path.read_bytes()
        cont7_plan = json.loads(cont7_raw)
        cont7_receipt = json.loads(cont7_receipt_path.read_bytes())
        cont7_gates = [row for row in _journal_rows(root / "release-gate.jsonl")
                       if row.get("plan_sha256") == sha256(cont7_raw).hexdigest()]
        cont7_releases = [row for row in releases
            if row.get("kind") == "continuation_released" and
               row.get("plan_sha256") == sha256(cont7_raw).hexdigest()]
        if (cont7_receipt.get("plan_sha256") != sha256(cont7_raw).hexdigest() or
                cont7_receipt.get("source_tree") != cont7_plan["source_tree"] or
                len(cont7_gates) != 1 or
                cont7_gates[0].get("preflight_receipt_sha256") !=
                    sha256(cont7_receipt_path.read_bytes()).hexdigest() or
                len(cont7_releases) != 1 or
                cont7_releases[0].get("mounted_source") !=
                    cont7_receipt.get("mounted_source_identity") or
                cont7_releases[0].get("original_start_at") !=
                    started[0]["allowance"]["start_at"]):
            raise RuntimeError("seventh continuation source/release identity differs")
        if len(ended) != 84:
            raise RuntimeError("seventh continuation has a different completed-case count")
        completed = cont7_plan["cases"][77]
        row = ended[83]
        if ((completed["scenario_id"], completed["variant"]) != ("t62_e", "composed") or
                row.get("case_id") != completed["id"] or row.get("status") != "PASS" or
                row.get("scenario_id") != completed["scenario_id"] or
                row.get("variant") != completed["variant"]):
            raise RuntimeError("seventh continuation completed case differs")
        verified = verify_case_result(completed, row.get("result"), root,
            actual=row.get("actual_correlation"), require_actual=True)
        if verified["status"] != "PASS" or row.get("verification", {}).get("status") != "PASS":
            raise RuntimeError("seventh continuation PASS evidence changed")
        passed.append(completed["id"])
        unstarted = cont7_plan["cases"][len(passed)]
        requests = [item for item in journal
                    if item.get("kind") == "browser_capture_requested" and
                       item.get("case_id") == unstarted["id"]]
        if (len(passed) != 78 or
                (unstarted["scenario_id"], unstarted["variant"]) != ("t64", "composed") or
                unstarted["id"] != "case.t64.composed" or
                len(requests) != 1 or requests[0].get("at", 0) <= row.get("at", 0) or
                requests[0].get("source_tree") != cont7_plan["source_tree"] or
                requests[0].get("campaign_id") !=
                    cont7_plan["envelope"]["campaign_id"] or
                requests[0].get("operator_url") !=
                    row["campaign_after"]["endpoints"]["operator"] or
                requests[0].get("expected_evidence_path") !=
                    str(root / "operator-browser-evidence.json") or
                any(item.get("kind") in {"case_begin", "case_end"} and
                    item.get("case_id") == unstarted["id"] for item in journal) or
                (root / unstarted["evidence_paths"][0]).exists() or
                (root / "operator-browser-evidence.json").exists() or
                row["campaign_after"]["attempt_count"] != 91 or
                row["campaign_after"]["possible_send_count"] != 91 or
                row["campaign_after"]["cumulative_reserved_decimal"] !=
                    "0.027600030" or row["campaign_after"]["paused"] or
                row["receiver_arrivals_after"] != 80 or
                len(_journal_rows(root / "receiver.jsonl")) != 80):
            raise RuntimeError("T64 capture did not stop before case begin with unchanged exposure")
        failed_id = unstarted["id"]
        latest_failed = {"case_id": failed_id,
                         "campaign_after": row["campaign_after"]}
        failed_attempt_ids = []
        latest_evidence = None
        latest_plan_path = cont7_plan_path
    return {"passed_ids": passed, "failed_id": failed_id,
            "original_failed_id": failed["case_id"],
            "latest_failed_id": latest_failed["case_id"],
            "latest_failed_evidence": latest_evidence,
            "continuation_number": continuation_number,
            "failed_attempt_id": attempt_id,
            "failed_attempt_ids": failed_attempt_ids,
            "retained_t47_live_attempt_ids": retained_t47_live_attempt_ids,
            "retained_t47_live_evidence": retained_t47_live_evidence,
            "retained_t60_positive_attempt_ids": retained_t60_positive_attempt_ids,
            "failed_evidence": snapshot(evidence),
            "latest_plan_path": str(latest_plan_path),
            "original_plan_sha256": sha256(prior_plan_bytes).hexdigest(),
            "original_release_plan_sha256": identity["plan_sha256"],
            "original_source_tree": prior_plan["source_tree"],
            "original_mounted_source": releases[0].get("mounted_source"),
            "original_start_at": started[0]["allowance"]["start_at"],
            "original_expires_at": started[0]["allowance"]["expires_at"],
            "last_campaign": latest_failed["campaign_after"],
            "prior_journal_rows": len(journal)}


def build_continuation_plan(*, root: Path, prior_plan: dict,
                            checkpoint: dict) -> dict:
    """Create a successor prospectus without rewriting the original plan."""
    artifacts = {item["kind"]: item for item in prior_plan["artifacts"]}
    envelope = prior_plan["envelope"]
    plan = build_plan(root=root, wheel=Path(artifacts["python_wheel"]["path"]),
        js_package=Path(artifacts["js_tarball"]["path"]),
        service_image=artifacts["service_image"]["path"],
        node_image=artifacts["node_image"]["path"],
        operator_port=envelope["operator_port"],
        campaign_id=envelope["campaign_id"],
        budget_account_id=envelope["budget_account_id"],
        financial_owner_id=envelope["financial_owner_id"])
    if plan["artifacts"] != prior_plan["artifacts"] or \
            {k: v for k, v in plan["envelope"].items() if k != "preexisting_exposure_decimal"} != \
            {k: v for k, v in envelope.items() if k != "preexisting_exposure_decimal"}:
        raise RuntimeError("continuation changes frozen inputs or finite allowance")
    previous_pairs = [(case["scenario_id"], case["variant"]) for case in prior_plan["cases"]]
    current_pairs = [(case["scenario_id"], case["variant"]) for case in plan["cases"]]
    if previous_pairs != current_pairs:
        raise RuntimeError("continuation changes selected case order")
    inherited_ids = {}
    if checkpoint["continuation_number"] >= 3:
        prior_successor_path = Path(checkpoint["latest_plan_path"])
        if not prior_successor_path.is_file() or prior_successor_path.is_symlink():
            raise RuntimeError("latest reviewed continuation plan absent")
        prior_successor = json.loads(prior_successor_path.read_bytes())
        if ([(row["scenario_id"], row["variant"]) for row in prior_successor["cases"]]
                != current_pairs or prior_successor["artifacts"] != plan["artifacts"]):
            raise RuntimeError("latest continuation plan differs from selected inventory")
        for case, predecessor in zip(plan["cases"], prior_successor["cases"]):
            inherited_ids[case["id"]] = predecessor["id"]
            case["id"] = predecessor["id"]
            case["evidence_paths"] = predecessor["evidence_paths"]
            if predecessor["id"] in checkpoint["passed_ids"]:
                case["max_admissions"] = predecessor["max_admissions"]
                case["max_possible_sends"] = predecessor["max_possible_sends"]
                case["max_exposure_decimal"] = predecessor["max_exposure_decimal"]
    old_id = checkpoint["failed_id"]
    new_id = old_id + ".continuation" + str(checkpoint["continuation_number"])
    for case in plan["cases"]:
        case["prerequisites"] = [new_id if value == old_id else inherited_ids.get(value, value)
                                 for value in case["prerequisites"]]
        case["late_dependencies"] = [new_id if value == old_id else inherited_ids.get(value, value)
                                     for value in case["late_dependencies"]]
        if case["id"] == old_id:
            case["id"] = new_id
            case["evidence_paths"] = ["cases/" + new_id + ".json"]
            case["max_admissions"] = 0
            case["max_possible_sends"] = 0
            case["max_exposure_decimal"] = "0.000000000"
    plan["envelope"]["preexisting_exposure_decimal"] = checkpoint[
        "last_campaign"]["cumulative_reserved_decimal"]
    return plan


@dataclass
class CompletionRuntime:
    """One disposable, isolated assembly for one finite parent campaign."""

    plan: dict
    root: Path
    handlers: dict

    def __post_init__(self):
        self.store = None
        self.coordinator = None
        self.receiver = None
        self.wire = None
        self.operator = None
        self.allowance = None
        self.authority = None
        self.registry = None
        self.operator_credentials = {}
        self.executor = None
        self.contexts_by_credential = {}
        self.credentials = {}
        self.journal = self.root / "case-journal.jsonl"
        self.receiver_log = self.root / "receiver.jsonl"
        self.guard_log = self.root / "guard.jsonl"
        self.started = False

    @staticmethod
    def _wait_port(process, port: int):
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("controlled TLS receiver stopped during startup")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=.1):
                    return
            except OSError:
                time.sleep(.05)
        raise TimeoutError("controlled TLS receiver readiness")

    @staticmethod
    def _operator_port(envelope: dict, free_port) -> int:
        declared = os.environ.get("DEV12_OPERATOR_PORT")
        if declared is None:
            if "operator_port" in envelope:
                raise RuntimeError("planned operator port requires exact runtime declaration")
            return free_port()
        if (not declared.isascii() or not declared.isdecimal() or
                type(envelope.get("operator_port")) is not int or
                int(declared) != envelope["operator_port"] or
                not 1024 <= int(declared) <= 65535):
            raise RuntimeError("fixed operator port differs from exact plan")
        port = int(declared)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
        return port

    def _bind_contexts(self):
        """Use A1 vectors for three distinct, synthetic authenticated roles."""
        from dev12_integrated import fixture
        identities = ("DIRECT_DOCUMENT", "DELEGATED_RERANK", "AUTONOMOUS_QUERY")
        for index, vector_id in enumerate(identities):
            request, context = fixture(vector_id)
            context["identity"]["charging_owner_id"] = self.plan["envelope"]["financial_owner_id"]
            token = f"dev12.completion02.synthetic.{index}." + "x" * 32
            if vector_id == "DIRECT_DOCUMENT":
                retained = self.root / "continuation-direct-secret.json"
                if retained.exists():
                    if retained.is_symlink() or retained.stat().st_mode & 0o077:
                        raise RuntimeError("retained disposable direct credential unsafe")
                    token = json.loads(retained.read_text())["direct"]
            self.credentials[vector_id] = token
            self.contexts_by_credential[token] = context
        return {token: {**context["identity"],
                        "task_id": fixture(vector_id)[0]["work_selector"]["task_id"],
                        "expires_at": context["expires_at"]}
                for vector_id, token in self.credentials.items()
                for context in (self.contexts_by_credential[token],)}

    def persist_signer(self, private_key, version: str) -> Path:
        """Retain synthetic rotation material before authority publishes its selector."""
        from cryptography.hazmat.primitives import serialization
        if not version.startswith("v.") or not version.replace(".", "").isalnum():
            raise ValueError("bounded synthetic signer version required")
        path = self.root / ("signing-key-" + version + ".pem")
        raw = private_key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        path.chmod(0o600)
        return path

    def _ensure_continuation_other_credential(self) -> None:
        """Recover only the disposable ordinary login when its case needs it."""
        if self.operator_credentials.get("other"):
            return
        credential_file = self.root / "continuation-operator-secret.json"
        if credential_file.exists():
            if credential_file.is_symlink() or credential_file.stat().st_mode & 0o077:
                raise RuntimeError("retained synthetic operator secret is unsafe")
            other_secret = json.loads(credential_file.read_text())["other"]
        else:
            principals = [item for item in self.registry.list_principals()
                          if item["principal_id"] == "user.other.synthetic"]
            if len(principals) != 1:
                raise RuntimeError("original synthetic ordinary principal absent")
            # An earlier disposable continuation can stop after registry
            # rotation but before the one-time secret is retained. Bind each
            # recovery operation to the observed principal revision so a lost
            # synthetic secret can be rotated again without replaying an
            # already committed one-use operation.
            revision = principals[0]["revision"]
            _, other_secret = self.registry.provision_credential("owner.local",
                "user.other.synthetic", revision,
                "op.dev12.completion02.credential.other.revision." + str(revision))
            if not other_secret:
                raise RuntimeError("synthetic ordinary credential cannot be recovered")
            raw = _json_bytes({"other": other_secret})
            with os.fdopen(os.open(credential_file,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
                if stream.write(raw) != len(raw):
                    raise OSError("short synthetic credential write")
                stream.flush()
                os.fsync(stream.fileno())
            append_durable(self.journal, {"kind": "continuation_synthetic_credential_rotated",
                "at": time.time_ns(), "principal_id": "user.other.synthetic",
                "purpose": "T-62.e isolated cross-principal read check"})
        self.operator_credentials["other"] = other_secret

    def _install_exact_clients(self):
        """Unpack reviewed artifact bytes locally, with no package acquisition."""
        artifacts = {row["kind"]: Path(row["path"]) for row in self.plan["artifacts"]}
        self.installed_python_root = self.root / "installed-python"
        self.installed_js_root = (self.root / "installed-js" / "node_modules" /
                                  "@mach33" / "duranki-client")
        self.installed_python_root.mkdir()
        self.installed_js_root.mkdir(parents=True)
        with zipfile.ZipFile(artifacts["python_wheel"]) as package:
            for member in package.infolist():
                destination = Path(member.filename)
                if (destination.is_absolute() or ".." in destination.parts or
                        member.is_dir() and member.file_size):
                    raise ValueError("unsafe Python wheel member")
                target = self.installed_python_root / destination
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with package.open(member) as source, target.open("xb") as output:
                        output.write(source.read())
        with tarfile.open(artifacts["js_tarball"], "r:gz") as package:
            for member in package:
                destination = Path(member.name)
                if (destination.is_absolute() or ".." in destination.parts or
                        not destination.parts or destination.parts[0] != "package" or
                        not (member.isfile() or member.isdir())):
                    raise ValueError("unsafe CommonJS package member")
                target = self.installed_js_root.joinpath(*destination.parts[1:])
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with package.extractfile(member) as source, target.open("xb") as output:
                        output.write(source.read())
        sys.path.insert(0, str(self.installed_python_root))

    def start(self, *, finite_scope=None):
        """Called only after a passing no-send preflight and explicit release."""
        if self.started:
            raise RuntimeError("campaign assembly already started")
        if (self.root / "campaign.sqlite").exists() or self.journal.exists():
            raise RuntimeError("existing durable campaign requires continuation, not reset")
        if finite_scope is not None:
            if self.plan["envelope"]["campaign_id"] == "campaign.dev12.c02.ct02b.supp02":
                from dev12_ct02b_supp02 import supplemental_limits
            else:
                from dev12_ct02b_supplement import supplemental_limits
            supplemental_limits(self.plan, finite_scope)
        sys.path[:0] = [str(ROOT / "server/src"), str(HERE),
                        str(ROOT / "tests/development_slice")]
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519
        from duranki_server.core import Coordinator
        from duranki_server.operator_projection import OperatorProjection
        from duranki_server.operator_web import serve as serve_operator
        from duranki_server.registry import Registry
        from duranki_server.store import SQLiteStore
        from duranki_server.successor_assembly import attach_standalone_synthetic
        from duranki_server.successor_authority import SyntheticSuccessorAuthority
        from duranki_server.successor_campaign import FiniteSuccessorCampaign
        from duranki_server.successor_receiver_evidence import DurableReceiverReceipts
        from duranki_server.web import serve
        from dev12_executor import Dev12SyntheticExecutor
        from dev12_integrated import certificate, free_port
        from dev12_completion_preflight import mounted_source_identity
        from dev12_tls_receiver import TEST_KEY

        envelope = self.plan["envelope"]
        if (envelope.get("service_network_mode") != "bridge" or
                os.environ.get("DEV12_SERVICE_NETWORK_MODE") != "bridge"):
            raise RuntimeError("browser-qualified service requires declared Docker bridge identity")
        worker = Path(os.environ.get("DEV12_WORKER_SOCKET", "/link/dev12-worker.sock"))
        if not worker.is_socket():
            raise RuntimeError("isolated worker socket absent")
        self._install_exact_clients()
        cert, key = certificate(self.root)
        receiver_port, service_port = free_port(), free_port()
        operator_port = self._operator_port(envelope, free_port)
        self.receiver_port = receiver_port
        self.service_port = service_port
        self.operator_port = operator_port
        self.base_url = f"http://127.0.0.1:{service_port}"
        self.operator_url = f"http://127.0.0.1:{operator_port}"
        identities = self._bind_contexts()
        signer = ed25519.Ed25519PrivateKey.generate()
        signing_path = self.root / "signing-key.pem"
        signing_path.write_bytes(signer.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))
        signing_path.chmod(0o600)
        self.receiver = subprocess.Popen((sys.executable, "-I", "-B",
            str(HERE / "dev12_completion_receiver.py"), str(cert), str(key),
            str(self.receiver_log), str(receiver_port)), cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=(self.root / "receiver.stderr").open("ab"))
        self._wait_port(self.receiver, receiver_port)
        self.store = SQLiteStore(self.root / "campaign.sqlite")
        self.authority = SyntheticSuccessorAuthority(self.store, signer,
                                                     "key.synthetic.dev12", "v1")
        direct = self.contexts_by_credential[self.credentials["DIRECT_DOCUMENT"]]["identity"]
        self.registry = Registry(self.store, self.authority,
            legacy_destination={"configuration_ref": "cfg.synthetic.dev12.operator",
                "service": "controlled.synthetic", "endpoint": "127.0.0.1",
                "model": "model.demo", "model_version": "synthetic-v1",
                "processing_region": "local"},
            legacy_token=self.credentials["DIRECT_DOCUMENT"], legacy_trusted=direct)
        ordinary = self.registry.mutate("owner.local", {
            "operation_id": "op.dev12.completion02.create.other",
            "action": "create_principal", "subject": "user.other.synthetic",
            "expected_revision": 0,
            "data": {"display_name": "Other synthetic user", "kind": "human",
                     "owner": "owner.local"}})["record"]
        ordinary, other_secret = self.registry.provision_credential(
            "owner.local", ordinary["principal_id"], ordinary["revision"],
            "op.dev12.completion02.credential.other")
        self.registry.mutate("owner.local", {
            "operation_id": "op.dev12.completion02.activate.other",
            "action": "principal_state", "subject": ordinary["principal_id"],
            "expected_revision": ordinary["revision"],
            "data": {"status": "active", "reason": "isolated qualification"}})
        self.operator_credentials = {"owner": "dev12.synthetic.operator." + "x" * 32,
                                     "other": other_secret}
        for context in self.contexts_by_credential.values():
            self.authority.set_historical_access(context["identity"], read=True,
                write=True, resume=True,
                observed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        self.allowance = FiniteSuccessorCampaign(self.store, envelope["campaign_id"],
            envelope["budget_account_id"],
            financial_owner_id=envelope["financial_owner_id"])
        identity = mounted_source_identity()
        retained = {"plan_sha256": sha256(_json_bytes(self.plan)).hexdigest(),
            "source_tree": self.plan["source_tree"], "mounted_source": identity,
            "artifacts": self.plan["artifacts"], "campaign_id": envelope["campaign_id"],
            "receiver": f"127.0.0.1:{receiver_port}",
            "service": self.base_url, "operator": self.operator_url,
            "planned_operator_port": envelope.get("operator_port"),
            "service_network_mode": "bridge",
            "service_default_route_present": any(
                row.split()[1] == "00000000" for row in
                Path("/proc/net/route").read_text().splitlines()[1:]),
            "worker_network_mode": "none",
            "worker_socket": str(worker), "real_provider_calls": 0}
        append_durable(self.root / "release-identity.jsonl", retained)
        if finite_scope is None:
            limits = {"max_attempts": 512, "max_concurrent": 2,
                      "ceiling_decimal": "6.000000000", "window_hours": 24}
        else:
            limits = supplemental_limits(self.plan, finite_scope)
        self.allowance.start({"receiver": retained["receiver"], "service": self.base_url,
                              "operator": self.operator_url},
            ["campaign.sqlite", "receiver.jsonl", "receiver-receipts.jsonl",
             "guard.jsonl", "case-journal.jsonl", str(worker)],
            **limits)
        if finite_scope is not None:
            if self.plan["envelope"]["campaign_id"] == "campaign.dev12.c02.ct02b.supp02":
                from dev12_ct02b_supp02 import verify_started_limits
            else:
                from dev12_ct02b_supplement import verify_started_limits
            verify_started_limits(self.allowance.inspect(), finite_scope)
        self.executor = Dev12SyntheticExecutor(worker, receiver_port,
                                               cert.read_text(), TEST_KEY)
        os.environ["DURANKI_DEV04_GUARD_EVENTS"] = str(self.guard_log)
        def permitted(current, original):
            return (current["principal_id"] == original["work_key"]["principal_id"] and
                    current["source_authority_id"] ==
                    original["trusted_identity"]["source_authority_id"] and
                    current["identity_binding_id"] ==
                    original["trusted_identity"]["identity_binding_id"])
        self.coordinator = Coordinator(self.store, identities, {}, {}, {}, None,
                                       None, {}, {}, None)
        self.successor = attach_standalone_synthetic(self.coordinator,
            store=self.store, contexts_by_credential=self.contexts_by_credential,
            authority=self.authority, executor=self.executor,
            allowance=self.allowance, read_allowed=permitted,
            usage_write_allowed=permitted,
            receiver_receipts=DurableReceiverReceipts(
                self.root / "receiver-receipts.jsonl"))
        self.successor.recover_incomplete()
        self.wire = serve("127.0.0.1", service_port, self.coordinator)
        threading.Thread(target=self.wire.serve_forever, daemon=True).start()
        # Docker publishes this container listener only on the host's 127.0.0.1.
        # Binding container loopback would make the published port unreachable.
        self.operator = serve_operator("0.0.0.0", operator_port,
            projection=OperatorProjection(self.store, "user.demo",
                                          str(self.root / "send-events.jsonl")),
            runner=None, password=self.operator_credentials["owner"],
            fixture={"destination": {}, "policy": {}},
            build={"commit": "disposable.dev12", "dirty": False,
                   "fingerprint": identity["sha256"]},
            web_root=ROOT / "web", worker_probe=lambda: {"state": "networkless"},
            sender_status=lambda: {"state": "controlled"}, successor_store=self.store,
            registry=self.registry)
        threading.Thread(target=self.operator.serve_forever, daemon=True).start()
        self.started = True
        append_durable(self.journal, {"kind": "campaign_started", "at": time.time_ns(),
                                     "identity": retained,
                                     "allowance": self.allowance.inspect()})

    def continue_existing(self, checkpoint: dict, receipt: dict) -> None:
        """Reopen one stopped campaign; never start, reseed, or replay it."""
        if self.started or not (self.root / "campaign.sqlite").is_file():
            raise RuntimeError("continuation requires one stopped durable campaign")
        sys.path[:0] = [str(ROOT / "server/src"), str(HERE),
                        str(ROOT / "tests/development_slice")]
        from cryptography.hazmat.primitives import serialization
        from duranki_server.core import Coordinator
        from duranki_server.operator_projection import OperatorProjection
        from duranki_server.operator_web import serve as serve_operator
        from duranki_server.registry import Registry
        from duranki_server.store import SQLiteStore
        from duranki_server.successor_assembly import attach_standalone_synthetic
        from duranki_server.successor_authority import SyntheticSuccessorAuthority
        from duranki_server.successor_campaign import FiniteSuccessorCampaign
        from duranki_server.successor_receiver_evidence import DurableReceiverReceipts
        from duranki_server.web import serve
        from dev12_executor import Dev12SyntheticExecutor
        from dev12_integrated import certificate, free_port
        from dev12_completion_preflight import mounted_source_identity
        from dev12_tls_receiver import TEST_KEY
        from cryptography import x509
        import sqlite3

        envelope = self.plan["envelope"]
        if (envelope.get("service_network_mode") != "bridge" or
                os.environ.get("DEV12_SERVICE_NETWORK_MODE") != "bridge"):
            raise RuntimeError("continuation service network declaration differs")
        worker = Path(os.environ.get("DEV12_WORKER_SOCKET", "/link/dev12-worker.sock"))
        if not worker.is_socket() or not os.access(worker, os.W_OK):
            raise RuntimeError("original isolated worker socket unavailable to service UID")
        self.installed_python_root = self.root / "installed-python"
        self.installed_js_root = (self.root / "installed-js" / "node_modules" /
                                  "@mach33" / "duranki-client")
        for installed in (self.installed_python_root, self.installed_js_root):
            if not installed.is_dir() or installed.is_symlink():
                raise RuntimeError("original exact installed-client extraction absent")
        sys.path.insert(0, str(self.installed_python_root))
        cert, key = self.root / "cert.pem", self.root / "key.pem"
        for item in (cert, key):
            if not item.is_file() or item.is_symlink():
                raise RuntimeError("original controlled receiver TLS material absent")
        original_cert_sha256 = sha256(cert.read_bytes()).hexdigest()
        expiration = x509.load_pem_x509_certificate(cert.read_bytes()).not_valid_after.replace(
            tzinfo=timezone.utc)
        renewed_tls = expiration <= datetime.now(timezone.utc) + timedelta(minutes=5)
        if renewed_tls:
            # A short-lived synthetic receiver certificate is not campaign
            # authority. Retain the original bytes and use a distinct identity.
            cert, key = certificate(self.root,
                stem="receiver.continue" + str(time.time_ns()), valid_hours=24)
        self.receiver_certificate = {"path": str(cert.relative_to(self.root)),
            "sha256": sha256(cert.read_bytes()).hexdigest(),
            "original_sha256": original_cert_sha256,
            "renewed": renewed_tls}
        self.receiver_port, self.service_port = free_port(), free_port()
        self.operator_port = self._operator_port(envelope, free_port)
        self.base_url = f"http://127.0.0.1:{self.service_port}"
        self.operator_url = f"http://127.0.0.1:{self.operator_port}"
        identities = self._bind_contexts()
        with sqlite3.connect(f"file:{self.root / 'campaign.sqlite'}?immutable=1", uri=True) as db:
            row = db.execute("SELECT state FROM dev12_authority WHERE "
                "authority_id='standalone.synthetic'").fetchone()
        if row is None:
            raise RuntimeError("original durable authority absent")
        active = json.loads(row[0])["active_minting_key"]
        version = active["key_version"]
        signer_path = (self.root / "signing-key.pem" if version == "v1" else
                       self.root / ("signing-key-" + version + ".pem"))
        if not signer_path.is_file() or signer_path.is_symlink():
            raise RuntimeError("exact durable active signer unavailable")
        signer = serialization.load_pem_private_key(signer_path.read_bytes(), password=None)
        self.store = SQLiteStore(self.root / "campaign.sqlite")
        self.authority = SyntheticSuccessorAuthority(self.store, signer,
            active["key_id"], version)
        direct = self.contexts_by_credential[self.credentials["DIRECT_DOCUMENT"]]["identity"]
        self.registry = Registry(self.store, self.authority,
            legacy_destination={"configuration_ref": "cfg.synthetic.dev12.operator",
                "service": "controlled.synthetic", "endpoint": "127.0.0.1",
                "model": "model.demo", "model_version": "synthetic-v1",
                "processing_region": "local"},
            legacy_token=self.credentials["DIRECT_DOCUMENT"], legacy_trusted=direct)
        self.allowance = FiniteSuccessorCampaign(self.store, envelope["campaign_id"],
            envelope["budget_account_id"],
            financial_owner_id=envelope["financial_owner_id"])
        before = self.allowance.inspect()
        expected = checkpoint["last_campaign"]
        for field in ("campaign_id", "budget_account_id", "financial_owner_id",
                      "currency", "ceiling_decimal", "max_attempts", "max_concurrent",
                      "start_at", "expires_at", "attempt_count", "possible_send_count",
                      "cumulative_reserved_decimal"):
            if before.get(field) != expected.get(field):
                raise RuntimeError("durable campaign differs from stopped checkpoint: " + field)
        if before["expires_at"] != checkpoint["original_expires_at"] or \
                datetime.now(timezone.utc) >= datetime.strptime(before["expires_at"],
                    "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc):
            raise RuntimeError("original finite release window expired")
        self.operator_credentials = {"owner": "dev12.synthetic.operator." + "x" * 32}
        self.receiver = subprocess.Popen((sys.executable, "-I", "-B",
            str(HERE / "dev12_completion_receiver.py"), str(cert), str(key),
            str(self.receiver_log), str(self.receiver_port)), cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=(self.root / "receiver.stderr").open("ab"))
        self._wait_port(self.receiver, self.receiver_port)
        self.executor = Dev12SyntheticExecutor(worker, self.receiver_port,
                                               cert.read_text(), TEST_KEY)
        os.environ["DURANKI_DEV04_GUARD_EVENTS"] = str(self.guard_log)
        def permitted(current, original):
            return (current["principal_id"] == original["work_key"]["principal_id"] and
                    current["source_authority_id"] ==
                    original["trusted_identity"]["source_authority_id"] and
                    current["identity_binding_id"] ==
                    original["trusted_identity"]["identity_binding_id"])
        self.coordinator = Coordinator(self.store, identities, {}, {}, {}, None,
                                       None, {}, {}, None)
        self.successor = attach_standalone_synthetic(self.coordinator,
            store=self.store, contexts_by_credential=self.contexts_by_credential,
            authority=self.authority, executor=self.executor,
            allowance=self.allowance, read_allowed=permitted,
            usage_write_allowed=permitted,
            receiver_receipts=DurableReceiverReceipts(
                self.root / "receiver-receipts.jsonl"))
        arrivals_before = len(self.receiver_log.read_bytes().splitlines())
        self.successor.recover_incomplete()
        after = self.allowance.inspect()
        arrivals_after = len(self.receiver_log.read_bytes().splitlines())
        for field in ("start_at", "expires_at", "attempt_count",
                      "possible_send_count", "cumulative_reserved_decimal"):
            if after[field] != before[field]:
                raise RuntimeError("recovery changed finite campaign boundary: " + field)
        if arrivals_after != arrivals_before:
            raise RuntimeError("continuation recovery replayed receiver work")
        self.wire = serve("127.0.0.1", self.service_port, self.coordinator)
        threading.Thread(target=self.wire.serve_forever, daemon=True).start()
        source = mounted_source_identity()
        if source != receipt["mounted_source_identity"]:
            raise RuntimeError("continued assembly differs from new host source receipt")
        self.operator = serve_operator("0.0.0.0", self.operator_port,
            projection=OperatorProjection(self.store, "user.demo",
                str(self.root / "send-events.jsonl")),
            runner=None, password=self.operator_credentials["owner"],
            fixture={"destination": {}, "policy": {}},
            build={"commit": "disposable.dev12", "dirty": False,
                   "fingerprint": source["sha256"]},
            web_root=ROOT / "web", worker_probe=lambda: {"state": "networkless"},
            sender_status=lambda: {"state": "controlled"}, successor_store=self.store,
            registry=self.registry)
        threading.Thread(target=self.operator.serve_forever, daemon=True).start()
        self.started = True
        retained = {"kind": "continuation_released", "at": time.time_ns(),
            "original_plan_sha256": checkpoint["original_plan_sha256"],
            "original_source_tree": checkpoint["original_source_tree"],
            "original_mounted_source": checkpoint["original_mounted_source"],
            "plan_sha256": receipt["plan_sha256"], "source_tree": self.plan["source_tree"],
            "mounted_source": source, "campaign_id": envelope["campaign_id"],
            "original_start_at": checkpoint["original_start_at"],
            "original_expires_at": checkpoint["original_expires_at"],
            "original_attempt_count": before["attempt_count"],
            "original_possible_send_count": before["possible_send_count"],
            "receiver_arrivals_before": arrivals_before,
            "receiver_arrivals_after": arrivals_after,
            "receiver": f"127.0.0.1:{self.receiver_port}",
            "service": self.base_url, "operator": self.operator_url,
            "worker_socket": str(worker), "service_network_mode": "bridge",
            "receiver_certificate": self.receiver_certificate,
            "synthetic_ordinary_credential_rotated": False,
            "real_provider_calls": 0}
        append_durable(self.root / "release-identity.jsonl", retained)
        append_durable(self.journal, retained)

    def close(self):
        for server in (self.operator, self.wire):
            if server is not None:
                server.shutdown()
                server.server_close()
        if self.operator is not None:
            self.operator.operator_jobs.shutdown(wait=True)
        if self.coordinator is not None:
            self.coordinator.pool.shutdown(wait=True)
            self.coordinator.successor.pool.shutdown(wait=True)
        if self.receiver is not None:
            self.receiver.terminate()
            self.receiver.wait(timeout=5)
        if self.store is not None:
            self.store.close()

    def restart_service(self) -> dict:
        """Reopen the same SQLite campaign and recover without invoking any send.

        The receiver and isolated worker remain live. The old Coordinator and
        operator listeners are closed before any store object is replaced.
        The durable campaign row is read, never started or reseeded again.
        """
        if not self.started or self.executor.first_write_wait is not None:
            raise RuntimeError("service restart requires quiescent live assembly")
        from cryptography.hazmat.primitives import serialization
        from duranki_server.core import Coordinator
        from duranki_server.operator_projection import OperatorProjection
        from duranki_server.operator_web import serve as serve_operator
        from duranki_server.registry import Registry
        from duranki_server.store import SQLiteStore
        from duranki_server.successor_assembly import attach_standalone_synthetic
        from duranki_server.successor_authority import SyntheticSuccessorAuthority
        from duranki_server.successor_campaign import FiniteSuccessorCampaign
        from duranki_server.successor_receiver_evidence import DurableReceiverReceipts
        from duranki_server.web import serve
        import sqlite3

        before = self.allowance.inspect()
        arrivals_before = len(self.receiver_log.read_bytes().splitlines())
        append_durable(self.journal, {"kind": "service_restart_begin", "at": time.time_ns(),
            "campaign": before, "receiver_arrivals": arrivals_before})
        for listener in (self.operator, self.wire):
            listener.shutdown()
            listener.server_close()
        self.operator.operator_jobs.shutdown(wait=True)
        self.coordinator.pool.shutdown(wait=True)
        self.successor.pool.shutdown(wait=True)
        self.store.close()

        with sqlite3.connect(self.root / "campaign.sqlite") as db:
            state_row = db.execute("SELECT state FROM dev12_authority WHERE "
                "authority_id='standalone.synthetic'").fetchone()
        if state_row is None:
            raise RuntimeError("durable authority missing on same-campaign restart")
        active = json.loads(state_row[0])["active_minting_key"]
        version = active["key_version"]
        signer_path = (self.root / "signing-key.pem" if version == "v1" else
                       self.root / ("signing-key-" + version + ".pem"))
        if not signer_path.is_file() or signer_path.is_symlink():
            raise RuntimeError("durable active signer unavailable on restart")
        signer = serialization.load_pem_private_key(signer_path.read_bytes(), password=None)
        self.store = SQLiteStore(self.root / "campaign.sqlite")
        self.authority = SyntheticSuccessorAuthority(self.store, signer,
            active["key_id"], version)
        direct = self.contexts_by_credential[self.credentials["DIRECT_DOCUMENT"]]["identity"]
        self.registry = Registry(self.store, self.authority,
            legacy_destination={"configuration_ref": "cfg.synthetic.dev12.operator",
                "service": "controlled.synthetic", "endpoint": "127.0.0.1",
                "model": "model.demo", "model_version": "synthetic-v1",
                "processing_region": "local"},
            legacy_token=self.credentials["DIRECT_DOCUMENT"], legacy_trusted=direct)
        envelope = self.plan["envelope"]
        self.allowance = FiniteSuccessorCampaign(self.store, envelope["campaign_id"],
            envelope["budget_account_id"],
            financial_owner_id=envelope["financial_owner_id"])
        if (self.allowance.inspect()["start_at"] != before["start_at"] or
                self.allowance.inspect()["attempt_count"] != before["attempt_count"]):
            raise RuntimeError("same-campaign durable row changed during restart")
        def permitted(current, original):
            return (current["principal_id"] == original["work_key"]["principal_id"] and
                    current["source_authority_id"] ==
                    original["trusted_identity"]["source_authority_id"] and
                    current["identity_binding_id"] ==
                    original["trusted_identity"]["identity_binding_id"])
        identities = {token: {**context["identity"],
            "task_id": context["request"]["work_selector"]["task_id"]
            if "request" in context else None,
            "expires_at": context["expires_at"]}
            for token, context in self.contexts_by_credential.items()}
        # _bind_contexts uses the immutable fixed A1 vectors for task binding.
        from dev12_integrated import fixture
        for vector_id, token in self.credentials.items():
            identities[token]["task_id"] = fixture(vector_id)[0]["work_selector"]["task_id"]
        self.coordinator = Coordinator(self.store, identities, {}, {}, {}, None,
                                       None, {}, {}, None)
        self.successor = attach_standalone_synthetic(self.coordinator,
            store=self.store, contexts_by_credential=self.contexts_by_credential,
            authority=self.authority, executor=self.executor,
            allowance=self.allowance, read_allowed=permitted,
            usage_write_allowed=permitted,
            receiver_receipts=DurableReceiverReceipts(
                self.root / "receiver-receipts.jsonl"))
        self.successor.recover_incomplete()
        self.wire = serve("127.0.0.1", self.service_port, self.coordinator)
        threading.Thread(target=self.wire.serve_forever, daemon=True).start()
        from dev12_completion_preflight import mounted_source_identity
        self.operator = serve_operator("0.0.0.0", self.operator_port,
            projection=OperatorProjection(self.store, "user.demo",
                str(self.root / "send-events.jsonl")),
            runner=None, password=self.operator_credentials["owner"],
            fixture={"destination": {}, "policy": {}},
            build={"commit": "disposable.dev12", "dirty": False,
                   "fingerprint": mounted_source_identity()["sha256"]},
            web_root=ROOT / "web", worker_probe=lambda: {"state": "networkless"},
            sender_status=lambda: {"state": "controlled"},
            successor_store=self.store, registry=self.registry)
        threading.Thread(target=self.operator.serve_forever, daemon=True).start()
        after = self.allowance.inspect()
        arrivals_after = len(self.receiver_log.read_bytes().splitlines())
        if arrivals_after != arrivals_before or after["start_at"] != before["start_at"] or \
                after["possible_send_count"] != before["possible_send_count"]:
            raise AssertionError("service recovery changed receiver or send campaign identity")
        result = {"campaign_before": before, "campaign_after": after,
                  "receiver_arrivals_before": arrivals_before,
                  "receiver_arrivals_after": arrivals_after,
                  "authority_key_version": version}
        append_durable(self.journal, {"kind": "service_restart_end", "at": time.time_ns(),
            **result})
        return result

    def _correlation_snapshot(self):
        """Independent durable IDs and effective amounts at a case boundary."""
        with self.store._lock:
            submissions = {aid: (sid, json.loads(raw)) for sid, aid, raw in
                ((row[0], json.loads(row[1])["attempt_id"], row[1]) for row in
                 self.store.db.execute("SELECT submission_id,record FROM dev12_submissions"))}
            guards = {aid: (sid, json.loads(raw)) for aid, sid, raw in
                self.store.db.execute("SELECT attempt_id,submission_id,guard_receipt "
                                      "FROM dev12_send_ownership")}
            usage_rows = [(aid, revision, sid, json.loads(raw)) for aid, revision, sid, raw in
                self.store.db.execute("SELECT attempt_id,revision,submission_id,usage "
                                      "FROM dev12_usage_revisions")]
            campaign_attempts = {aid: {"state": state, "possible_send": bool(possible),
                "reservation_decimal": reserved} for aid, state, possible, reserved in
                self.store.db.execute("SELECT attempt_id,state,possible_send,reservation_decimal "
                                      "FROM dev12_campaign_attempts")}
        receiver_rows = [json.loads(line) for line in
            self.receiver_log.read_text().splitlines()] if self.receiver_log.exists() else []
        latest = {}
        for aid, revision, sid, row in usage_rows:
            if aid not in latest or revision > latest[aid][0]:
                latest[aid] = (revision, sid, row)
        known = sum((Decimal(row[2]["amount_decimal"]) for row in latest.values()
                     if row[2]["cost_status"] in {"calculated", "over_bound"}), Decimal(0))
        return {"submissions": submissions, "guards": guards,
                "usage_rows": usage_rows, "latest_usage": latest,
                "campaign_attempts": campaign_attempts,
                "receiver_rows": receiver_rows,
                "effective_known_decimal": known}

    def _verify_case_correlation(self, case, before, after,
                                 allowance_before, allowance_after, result):
        """Check actual receiver/guard/usage lineage and case financial allocation."""
        from duranki_server.successor_contract import usage_valid
        new_attempts = set(after["submissions"]) - set(before["submissions"])
        new_guards = set(after["guards"]) - set(before["guards"])
        new_usage = {(aid, revision) for aid, revision, _sid, _row in after["usage_rows"]} - \
                    {(aid, revision) for aid, revision, _sid, _row in before["usage_rows"]}
        arrivals = after["receiver_rows"][len(before["receiver_rows"]):]
        if (not new_guards.issubset(new_attempts) or
                len(arrivals) > case["max_possible_sends"] or
                len(new_attempts) > case["max_admissions"] or
                len(new_guards) > case["max_possible_sends"]):
            raise AssertionError("case admission/guard/receiver ID set exceeds exact scope")
        for aid in new_attempts:
            sid, record = after["submissions"][aid]
            campaign = after["campaign_attempts"].get(aid)
            if (record["contract_version"] != "0.3" or
                    record["campaign_id"] != self.allowance.campaign_id or
                    record["trusted_identity"]["charging_owner_id"] !=
                        self.plan["envelope"]["financial_owner_id"] or
                    record["reservation"]["budget_account_id"] !=
                        self.plan["envelope"]["budget_account_id"] or
                    campaign is None or
                    Decimal(campaign["reservation_decimal"]) !=
                        Decimal(record["reservation"]["max_exposure_decimal"])):
                raise AssertionError("new attempt differs from admitted campaign/owner/reservation")
        for aid in new_guards:
            sid, guard = after["guards"][aid]
            admitted_sid, record = after["submissions"][aid]
            if (sid != admitted_sid or guard["attempt_id"] != aid or
                    guard["plan_id"] != record["signed_plan"]["plan_id"] or
                    guard["work_digest"] != record["work_digest"] or
                    not after["campaign_attempts"][aid]["possible_send"]):
                raise AssertionError("guard does not bind admitted attempt and durable send allowance")
        arrival_ids = []
        for arrival in arrivals:
            aid = arrival["attempt_id"]
            arrival_ids.append(aid)
            if aid not in new_guards or aid not in after["submissions"]:
                raise AssertionError("receiver arrival has no same-case guarded attempt")
            _sid, record = after["submissions"][aid]
            _guard_sid, guard = after["guards"][aid]
            if (arrival["body_sha256"] != guard["body_sha256"] or
                    arrival["body_bytes"] != guard["body_bytes"] or
                    arrival["path"] != record["signed_plan"]["execution_descriptor"]["route"] or
                    arrival["request_valid"] is not True):
                raise AssertionError("receiver body/route differs from retained guard receipt")
        if len(arrival_ids) != len(set(arrival_ids)):
            raise AssertionError("duplicate receiver arrival for one case attempt")
        for aid, revision, sid, usage in after["usage_rows"]:
            if (aid, revision) not in new_usage:
                continue
            record_sid, record = after["submissions"].get(aid, (None, None))
            if (record is None or sid != record_sid or
                    not usage_valid(usage, record["request"], aid,
                        record["reservation"]["price_ref"],
                        record["reservation"]["usage_ref"],
                        record["reservation"]["max_exposure_decimal"])):
                raise AssertionError("new usage revision differs from original admitted scope")
        reserved_delta = (Decimal(allowance_after["cumulative_reserved_decimal"]) -
                          Decimal(allowance_before["cumulative_reserved_decimal"]))
        known_delta = (after["effective_known_decimal"] -
                       before["effective_known_decimal"])
        allocation = Decimal(case["max_exposure_decimal"])
        if (reserved_delta < 0 or reserved_delta > allocation or
                known_delta > allocation and case["phase"] not in {"late_evidence", "resume"}):
            raise AssertionError("case reservation/effective cost exceeds planned allocation")
        claimed_primary = None
        if result["observations"]:
            path = self.root / result["observations"][0]["evidence_path"]
            retained = json.loads(path.read_text())
            value = retained.get("actual_attempt_id")
            if value in new_attempts:
                claimed_primary = value
        if claimed_primary is None and len(new_attempts) == 1:
            claimed_primary = next(iter(new_attempts))
        primary_record = after["submissions"][claimed_primary][1] if claimed_primary else None
        terminal = primary_record["submission_state"] if primary_record else "completed"
        failure = primary_record.get("failure") if primary_record else None
        stage = primary_record.get("failure_stage") if primary_record else None
        mapped_stage = {"before_send": "first_write",
                        "result_validation": "delivery"}.get(stage, stage)
        rejection = ({"stage": mapped_stage, "code": failure["code"],
                      "http_status": (409 if stage == "before_send" else 502)}
                     if failure else None)
        primary_stages = []
        if claimed_primary:
            primary_stages.append("admission")
            if primary_record.get("signed_plan"):
                primary_stages.extend(("signed_plan", "authority"))
            if claimed_primary in after["guards"]:
                primary_stages.extend(("guard", "first_write"))
            if claimed_primary in arrival_ids:
                primary_stages.append("receiver")
            if primary_record.get("submission_state") in {"completed", "unknown"} or \
                    stage not in {"before_send", None}:
                primary_stages.append("delivery")
            # Financial history is separately validated even when delivery
            # validation failed; it is not evidence that execution progressed
            # beyond the rejected delivery boundary.
            if claimed_primary in after["latest_usage"] and not failure:
                primary_stages.append("settlement")
        return {"new_attempt_ids": sorted(new_attempts),
                "new_guard_attempt_ids": sorted(new_guards),
                "receiver_attempt_ids": arrival_ids,
                "new_usage_revisions": sorted([list(pair) for pair in new_usage]),
                "reserved_delta_decimal": str(reserved_delta),
                "effective_known_delta_decimal": str(known_delta),
                "primary_attempt_id": claimed_primary,
                "primary_stages": primary_stages,
                "reservation_delta_decimal": str(reserved_delta),
                "terminal_status": terminal,
                "rejection": rejection}

    def _repair_partial_write(self, case: dict, checkpoint: dict) -> tuple[dict, dict]:
        """Re-evaluate the retained failed attempt after a scoped product fix.

        This is a late, no-send continuation of the original partial-write
        attempt.  It never calls submit, invokes the transport, or allocates a
        second WorkKey. The original FAIL and its evidence remain immutable.
        """
        from dev12_completion_handlers import _evidence, _trusted
        if (case["scenario_id"], case["variant"], case["id"]) != (
                "t24_b", "partial_write", checkpoint["failed_id"] + ".continuation1"):
            raise RuntimeError("unregistered continuation repair case")
        original_path = Path(checkpoint["failed_evidence"]["path"])
        if snapshot(original_path) != checkpoint["failed_evidence"]:
            raise RuntimeError("original failed case evidence changed")
        original = json.loads(original_path.read_bytes())
        aid = checkpoint["failed_attempt_id"]
        old = original["payload"]
        admitted = old["record"]
        sid = admitted["submission_id"]
        if (original["actual_attempt_id"] != aid or
                admitted["attempt_id"] != aid or
                old["late"]["collection"] != "accepted" or
                old["reply"]["status"]["submission_state"] != "unknown"):
            raise RuntimeError("original partial-write attempt lineage differs")
        retained = self.store.successor_get(sid)
        before = self.allowance.inspect()
        census_before = self._correlation_snapshot()
        receiver_before = len(self.receiver_log.read_bytes().splitlines())
        if (retained["attempt_id"] != aid or
                retained["signed_plan"]["plan_id"] != admitted["signed_plan"]["plan_id"] or
                aid not in census_before["guards"] or
                sum(row.get("attempt_id") == aid for row in census_before["receiver_rows"]) != 1 or
                aid not in census_before["latest_usage"] or
                census_before["latest_usage"][aid][2]["cost_status"] != "calculated"):
            raise RuntimeError("retained guard, receiver and usage lineage incomplete")
        status = self.successor.status(sid, _trusted(self))
        resume = self.successor.resume_campaign(sid, _trusted(self),
            "continuation: original partial TLS write receipt and usage verified; no replay")
        after = self.allowance.inspect()
        census_after = self._correlation_snapshot()
        receiver_after = len(self.receiver_log.read_bytes().splitlines())
        no_send = (before["start_at"] == after["start_at"] == checkpoint["original_start_at"] and
            before["expires_at"] == after["expires_at"] == checkpoint["original_expires_at"] and
            before["attempt_count"] == after["attempt_count"] and
            before["possible_send_count"] == after["possible_send_count"] and
            before["cumulative_reserved_decimal"] == after["cumulative_reserved_decimal"] and
            receiver_before == receiver_after and
            census_before["submissions"] == census_after["submissions"] and
            census_before["guards"] == census_after["guards"] and
            census_before["usage_rows"] == census_after["usage_rows"])
        # The immutable original case document retained the actual transport
        # observations and the refused resume audit. The new audit is distinct.
        passed = (no_send and before["paused"] and not after["paused"] and
            resume.get("decision") == "resumed" and
            status.get("submission_state") == "unknown" and
            status.get("attempts", [{}])[0].get("usage_revision", {}).get(
                "cost_status") == "calculated" and
            old["late"]["resume"]["decision"] == "refused" and
            original["checks"]["t24_b.partial_write"]["passed"] is False and
            original["observed_stages"]["first_write"]["receiver_delta"] == 1)
        stages = dict(original["observed_stages"])
        stages["authority"] = {**stages["authority"],
            "continuation_resume_decision": resume.get("decision"),
            "original_refused_decision": old["late"]["resume"]["decision"]}
        result = _evidence(self, case, stages,
            {"t24_b.partial_write": (bool(passed),
                "Original guarded partial write and one receiver arrival retained; "
                "corrected campaign resume used the same late usage and made no new send")},
            {"continuation_of_case_id": checkpoint["failed_id"],
             "continuation_of_attempt_id": aid,
             "original_failed_evidence": checkpoint["failed_evidence"],
             "original_failed_resume_audit": old["late"]["resume"],
             "retained_record": retained, "status": status,
             "new_resume_audit": resume, "campaign_before": before,
             "campaign_after": after, "receiver_arrivals_before": receiver_before,
             "receiver_arrivals_after": receiver_after,
             "new_admissions": 0, "new_possible_sends": 0}, aid)
        actual = {"primary_attempt_id": aid, "terminal_status": "unknown",
            "rejection": None, "primary_stages": ["admission", "signed_plan",
                "authority", "guard", "first_write", "receiver", "delivery",
                "settlement"], "reservation_delta_decimal": "0.000000000",
            "continuation_of_case_id": checkpoint["failed_id"],
            "continuation_of_attempt_id": aid,
            "receiver_attempt_ids": [], "new_attempt_ids": [],
            "new_guard_attempt_ids": [], "new_usage_revisions": [],
            "effective_known_delta_decimal": "0.000000000"}
        return result, actual

    def _verify_resumed_partial_write(self, case: dict,
                                      checkpoint: dict) -> tuple[dict, dict]:
        """Read-only second continuation of the same guarded first write."""
        from dev12_completion_handlers import _evidence
        if (case["scenario_id"], case["variant"], case["id"]) != (
                "t24_b", "partial_write", checkpoint["failed_id"] + ".continuation2"):
            raise RuntimeError("unregistered second continuation case")
        original_ref = checkpoint["failed_evidence"]
        cont1_ref = checkpoint["latest_failed_evidence"]
        for ref in (original_ref, cont1_ref):
            if snapshot(Path(ref["path"])) != ref:
                raise RuntimeError("retained continuation evidence changed")
        original = json.loads(Path(original_ref["path"]).read_bytes())
        cont1 = json.loads(Path(cont1_ref["path"]).read_bytes())
        aid = checkpoint["failed_attempt_id"]
        sid = original["payload"]["record"]["submission_id"]
        audit = cont1["payload"]["new_resume_audit"]
        blockers = {item.removeprefix("unresolved_exposure:")
            for item in original["payload"]["late"]["resume"]["blockers"]
            if item.startswith("unresolved_exposure:")}
        before = self.allowance.inspect()
        correlated = self._correlation_snapshot()
        receiver_before = len(self.receiver_log.read_bytes().splitlines())
        retained = self.store.successor_get(sid)
        with self.store._lock:
            audits = [json.loads(row[0]) for row in self.store.db.execute(
                "SELECT record FROM dev12_campaign_audit WHERE campaign_id=?",
                (self.allowance.campaign_id,))]
        matching_audits = [row for row in audits if row == audit]
        reconciled = {item for item in blockers
            if item in correlated["submissions"] and
            correlated["submissions"][item][1].get("exposure_state") == "not_sent" and
            correlated["submissions"][item][1].get("dispatch_state") == "blocked" and
            correlated["submissions"][item][1].get("failure_stage") == "before_send" and
            correlated["submissions"][item][1].get("failure", {}).get("code") ==
                "FDC_REJECTED"}
        usage = correlated["latest_usage"].get(aid)
        fault = original["observed_stages"]["first_write"].get("fault", {})
        original_arrivals = [row for row in correlated["receiver_rows"]
                             if row.get("attempt_id") == aid]
        after = self.allowance.inspect()
        receiver_after = len(self.receiver_log.read_bytes().splitlines())
        passed = (len(blockers) == 3 and reconciled == blockers and
            set(audit.get("definite_no_send_reconciled", [])) == blockers and
            len(matching_audits) == 1 and audit.get("decision") == "resumed" and
            before == after == checkpoint["last_campaign"] and
            before["paused"] is False and
            before["attempt_count"] == before["possible_send_count"] == 11 and
            before["cumulative_reserved_decimal"] == "0.002900002" and
            receiver_before == receiver_after == 8 and len(original_arrivals) == 1 and
            aid in correlated["guards"] and retained["attempt_id"] == aid and
            retained["submission_state"] == "unknown" and
            usage is not None and usage[2]["cost_status"] == "calculated" and
            usage[2]["amount_decimal"] == "0.000200000" and
            fault.get("fired") is True and
            "SYNTHETIC_PARTIAL_TLS_RECORD_AFTER_FIRST_BYTE" in
                fault.get("observations", []) and
            "RESPONSE_DROPPED_AFTER_FRAGMENTED_REQUEST" in
                fault.get("observations", []))
        stages = dict(original["observed_stages"])
        stages["authority"] = {**stages["authority"],
            "retained_resume_audit_decision": audit.get("decision"),
            "definite_no_send_reconciled": sorted(reconciled)}
        result = _evidence(self, case, stages,
            {"t24_b.partial_write": (bool(passed),
                "Original first-write attempt retained one receiver arrival and calculated "
                "usage; audited resume reconciled three definite no-send rows without "
                "another admission, send, or charge")},
            {"continuation_of_case_id": checkpoint["latest_failed_id"],
             "continuation_of_attempt_id": aid,
             "original_failed_evidence": original_ref,
             "first_continuation_evidence": cont1_ref,
             "durable_resume_audit": audit, "durable_audit_matches": len(matching_audits),
             "definite_no_send_attempts": sorted(reconciled),
             "retained_record": retained, "effective_usage": usage[2] if usage else None,
             "campaign_before": before, "campaign_after": after,
             "receiver_arrivals_before": receiver_before,
             "receiver_arrivals_after": receiver_after,
             "new_admissions": 0, "new_possible_sends": 0}, aid)
        actual = {"primary_attempt_id": aid, "terminal_status": "unknown",
            "rejection": None, "primary_stages": ["admission", "signed_plan",
                "authority", "guard", "first_write", "receiver", "delivery",
                "settlement"], "reservation_delta_decimal": "0.000000000",
            "continuation_of_case_id": checkpoint["latest_failed_id"],
            "continuation_of_attempt_id": aid, "receiver_attempt_ids": [],
            "new_attempt_ids": [], "new_guard_attempt_ids": [],
            "new_usage_revisions": [], "effective_known_delta_decimal": "0.000000000"}
        return result, actual

    def _verify_installed_client_attempts(self, case: dict,
                                          checkpoint: dict) -> tuple[dict, dict]:
        """Reduce two retained live installed-client attempts without replay."""
        from dev12_completion_handlers import _evidence
        if (case["scenario_id"], case["variant"], case["id"]) != (
                "t47_a", "composed", checkpoint["failed_id"] + ".continuation3"):
            raise RuntimeError("unregistered installed-client continuation case")
        original_ref = checkpoint["latest_failed_evidence"]
        if snapshot(Path(original_ref["path"])) != original_ref:
            raise RuntimeError("retained installed-client evidence changed")
        original = json.loads(Path(original_ref["path"]).read_bytes())
        live = original["payload"]["live_target"]
        py_reply, py_status = live["python_reply"], live["python_status"]
        js_reply = live["commonjs_observed"]["reply"]
        js_status = live["commonjs_observed"]["status"]
        pairs = (("python_wheel", py_reply, py_status),
                 ("js_tarball", js_reply, js_status))
        before = self.allowance.inspect()
        correlated_before = self._correlation_snapshot()
        receiver_before = len(self.receiver_log.read_bytes().splitlines())
        per_client = []
        for kind, reply, status in pairs:
            aid, sid = reply["attempt_id"], reply["handle"]["submission_id"]
            stored_sid, record = correlated_before["submissions"].get(aid, (None, None))
            guard_sid, guard = correlated_before["guards"].get(aid, (None, None))
            usage = correlated_before["latest_usage"].get(aid)
            arrivals = [row for row in correlated_before["receiver_rows"]
                        if row.get("attempt_id") == aid]
            per_client.append({"kind": kind, "attempt_id": aid, "submission_id": sid,
                "stored_submission_id": stored_sid, "guard_submission_id": guard_sid,
                "reply_state": reply["state"],
                "status_state": status["submission_state"],
                "stored_state": record.get("submission_state") if record else None,
                "work_key_matches": (record.get("work_key") == reply["handle"]["work_key"]
                                     if record else False),
                "guard_binds_plan": (guard.get("plan_id") ==
                    record["signed_plan"]["plan_id"] if guard and record else False),
                "receiver_arrivals": len(arrivals),
                "receiver_body_matches_guard": (arrivals[0].get("body_sha256") ==
                    guard.get("body_sha256") if len(arrivals) == 1 and guard else False),
                "usage_status": usage[2].get("cost_status") if usage else None,
                "usage_amount": usage[2].get("amount_decimal") if usage else None,
                "status_usage_matches": (usage[2] == status["attempts"][0].get(
                    "usage_revision") if usage and status.get("attempts") else False),
                "reply_attempt_matches_status": (status.get("attempts", [{}])[0].get(
                    "attempt_id") == aid),
                "reply_handle_matches_status": (reply["handle"] == status.get("handle"))})
        after = self.allowance.inspect()
        correlated_after = self._correlation_snapshot()
        receiver_after = len(self.receiver_log.read_bytes().splitlines())
        unchanged = (before == after == checkpoint["last_campaign"] and
            correlated_before == correlated_after and receiver_before == receiver_after == 24)
        distinct = len({row["attempt_id"] for row in per_client}) == 2 and \
            len({row["submission_id"] for row in per_client}) == 2
        complete = all(row["stored_submission_id"] == row["submission_id"] and
            row["guard_submission_id"] == row["submission_id"] and
            row["reply_state"] == row["status_state"] == row["stored_state"] ==
                "completed" and row["work_key_matches"] and row["guard_binds_plan"] and
            row["receiver_arrivals"] == 1 and row["receiver_body_matches_guard"] and
            row["usage_status"] == "calculated" and row["status_usage_matches"] and
            row["reply_attempt_matches_status"] and row["reply_handle_matches_status"]
            for row in per_client)
        live_before, live_after = live["before"], live["after"]
        boundary = (live_after["campaign"] == before and
            live_after["campaign"]["attempt_count"] -
                live_before["campaign"]["attempt_count"] == 2 and
            live_after["campaign"]["possible_send_count"] -
                live_before["campaign"]["possible_send_count"] == 2 and
            live_after["receiver_arrivals"] - live_before["receiver_arrivals"] == 2 and
            live_after["campaign"]["cumulative_reserved_decimal"] == "0.008000003")
        package_identity = (original["payload"]["exact_installed_assets"] is True and
            live["commonjs_actor"]["exit"] == 0 and
            Path(original["payload"]["wheel_root"]) == self.installed_python_root and
            Path(original["payload"]["commonjs_root"]) == self.installed_js_root and
            set(original["checks"]) == set(case["predicates"]) and
            all(value["passed"] is True for value in original["checks"].values()))
        passed = unchanged and distinct and complete and boundary and package_identity
        checks = {name: (bool(passed),
            "Retained installed Python wheel and CommonJS tarball each completed one "
            "distinct guarded receiver attempt; status, usage, and campaign totals "
            "reconcile without resubmission") for name in case["predicates"]}
        stages = {"client": {"python_attempt_id": per_client[0]["attempt_id"],
            "commonjs_attempt_id": per_client[1]["attempt_id"],
            "two_distinct_completed_attempts": distinct and complete,
            "receiver_arrivals": receiver_before}}
        result = _evidence(self, case, stages, checks,
            {"continuation_of_case_id": checkpoint["latest_failed_id"],
             "original_failed_evidence": original_ref,
             "installed_client_attempts": per_client,
             "campaign_before": before, "campaign_after": after,
             "receiver_arrivals_before": receiver_before,
             "receiver_arrivals_after": receiver_after,
             "new_admissions": 0, "new_possible_sends": 0},
            per_client[0]["attempt_id"])
        actual = {"primary_attempt_id": per_client[0]["attempt_id"],
            "terminal_status": "completed", "rejection": None,
            "primary_stages": ["admission", "signed_plan", "authority", "guard",
                "first_write", "receiver", "delivery", "settlement"],
            "reservation_delta_decimal": "0.000000000",
            "receiver_attempt_ids": [], "new_attempt_ids": [],
            "new_guard_attempt_ids": [], "new_usage_revisions": [],
            "effective_known_delta_decimal": "0.000000000"}
        return result, actual

    def _verify_native_revision_history(self, case: dict,
                                        checkpoint: dict) -> tuple[dict, dict]:
        """Reduce the three retained native-evidence attempts without a send."""
        from dev12_completion_handlers import _evidence
        if (case["scenario_id"], case["variant"], case["id"]) != (
                "t49_d", "composed", checkpoint["failed_id"] + ".continuation4"):
            raise RuntimeError("unregistered native-evidence continuation case")
        original_ref = checkpoint["latest_failed_evidence"]
        if snapshot(Path(original_ref["path"])) != original_ref:
            raise RuntimeError("retained native-evidence case changed")
        original = json.loads(Path(original_ref["path"]).read_bytes())
        observations = original["payload"]["observations"]
        before = self.allowance.inspect()
        correlated_before = self._correlation_snapshot()
        receiver_before = len(self.receiver_log.read_bytes().splitlines())
        reduced = []
        for item in observations:
            reply = item["reply"]["reply"]
            status_before, status_after = item["status_before"], item["status_after"]
            aid, sid = reply["attempt_id"], reply["handle"]["submission_id"]
            stored_sid, record = correlated_before["submissions"].get(aid, (None, None))
            guard_sid, guard = correlated_before["guards"].get(aid, (None, None))
            revisions = sorted((revision, row) for row_aid, revision, row_sid, row in
                correlated_before["usage_rows"] if row_aid == aid and row_sid == sid)
            arrivals = [row for row in correlated_before["receiver_rows"]
                        if row.get("attempt_id") == aid]
            rev1 = status_before["attempts"][0]["usage_revision"]
            rev2 = status_after["attempts"][0]["usage_revision"]
            reduced.append({"attempt_id": aid, "submission_id": sid,
                "stored_submission_id": stored_sid, "guard_submission_id": guard_sid,
                "record_state": record.get("submission_state") if record else None,
                "record_result_retained": bool(record and record.get("result")),
                "guard_binds_plan": (guard.get("plan_id") ==
                    record["signed_plan"]["plan_id"] if guard and record else False),
                "receiver_arrivals": len(arrivals),
                "receiver_body_matches_guard": (arrivals[0].get("body_sha256") ==
                    guard.get("body_sha256") if len(arrivals) == 1 and guard else False),
                "revision_numbers": [revision for revision, _ in revisions],
                "first_usage_matches_retained": (revisions[0][1] == rev1
                    if len(revisions) == 2 else False),
                "effective_usage_matches_retained": (revisions[-1][1] == rev2
                    if len(revisions) == 2 else False),
                "first_usage": rev1, "effective_usage": rev2,
                "first_delivery_valid": (status_before["attempts"][0][
                    "delivery_state"] == "valid" and reply["state"] == "completed"),
                "effective_delivery_valid": (status_after["attempts"][0][
                    "delivery_state"] == "valid" and
                    status_after["submission_state"] == "completed"),
                "result_unchanged": (reply.get("result") ==
                    status_before["attempts"][0].get("result") ==
                    status_after["attempts"][0].get("result")),
                "receipt_collection": item.get("collection"),
                "audited_resume_decision": item.get("resume", {}).get("decision")})
        after = self.allowance.inspect()
        correlated_after = self._correlation_snapshot()
        receiver_after = len(self.receiver_log.read_bytes().splitlines())
        common = (len(reduced) == 3 and len({row["attempt_id"] for row in reduced}) == 3 and
            before == after == checkpoint["last_campaign"] and
            before["attempt_count"] == before["possible_send_count"] == 51 and
            before["cumulative_reserved_decimal"] == "0.012200008" and
            before["paused"] is False and receiver_before == receiver_after == 40 and
            correlated_before == correlated_after and
            all(row["stored_submission_id"] == row["guard_submission_id"] ==
                row["submission_id"] and row["record_state"] == "completed" and
                row["record_result_retained"] and row["guard_binds_plan"] and
                row["receiver_arrivals"] == 1 and row["receiver_body_matches_guard"] and
                row["revision_numbers"] == [1, 2] and
                row["first_usage_matches_retained"] and
                row["effective_usage_matches_retained"] and
                row["first_delivery_valid"] and row["effective_delivery_valid"] and
                row["result_unchanged"] and row["receipt_collection"] == "accepted" and
                row["audited_resume_decision"] == "resumed" and
                row["first_usage"]["cost_status"] == "unknown" and
                "amount_decimal" not in row["first_usage"] and
                row["effective_usage"]["cost_status"] == "calculated" and
                row["effective_usage"].get("previous_revision") == 1 and
                row["effective_usage"]["amount_decimal"] == "0.000200000"
                for row in reduced))
        invalid = (common and reduced[0]["first_usage"]["components"][0][
            "presence"] == "invalid" and
            "raw_digest" in reduced[0]["first_usage"]["components"][0])
        out_domain = (common and reduced[1]["first_usage"]["components"][0][
            "presence"] == "known" and
            reduced[1]["first_usage"]["components"][0]["quantity"] == 999999999 and
            reduced[1]["first_usage"]["components"][0]["evidence"] == "reported")
        contradictory = (common and reduced[2]["first_usage"]["components"][0][
            "presence"] == "known" and
            reduced[2]["first_usage"]["components"][0]["quantity"] == 0 and
            reduced[2]["first_usage"]["components"][0]["evidence"] == "reported")
        checks = {
            "t49_d.invalid_counter": (bool(invalid),
                "Malformed Unicode usage remained unknown with a digest and no amount; "
                "the retained result stayed delivered and revision two calculated once"),
            "t49_d.out_of_domain": (bool(out_domain),
                "Reported out-of-domain quantity 999999999 remained a known raw value "
                "with unknown cost and no amount until independent revision two"),
            "t49_d.contradictory_counter": (bool(contradictory),
                "Contradictory reported zero remained explicit and unpriced until "
                "independent revision two; no new attempt or send occurred")}
        stages = dict(original["observed_stages"])
        stages["settlement"] = {**stages["settlement"],
            "retained_revision_pairs": [row["revision_numbers"] for row in reduced],
            "out_of_domain_quantity": 999999999}
        result = _evidence(self, case, stages, checks,
            {"continuation_of_case_id": checkpoint["latest_failed_id"],
             "original_failed_evidence": original_ref,
             "native_evidence_attempts": reduced,
             "campaign_before": before, "campaign_after": after,
             "receiver_arrivals_before": receiver_before,
             "receiver_arrivals_after": receiver_after,
             "new_admissions": 0, "new_possible_sends": 0},
            reduced[0]["attempt_id"])
        actual = {"primary_attempt_id": reduced[0]["attempt_id"],
            "terminal_status": "completed", "rejection": None,
            "primary_stages": ["admission", "signed_plan", "authority", "guard",
                "first_write", "receiver", "delivery", "settlement"],
            "reservation_delta_decimal": "0.000000000",
            "receiver_attempt_ids": [], "new_attempt_ids": [],
            "new_guard_attempt_ids": [], "new_usage_revisions": [],
            "effective_known_delta_decimal": "0.000000000"}
        return result, actual

    def _verify_operator_identity_continuation(self, case: dict,
                                               checkpoint: dict) -> tuple[dict, dict]:
        """Finish authenticated T60 reads and preadmission negatives, no positives."""
        from copy import deepcopy
        from dev12_completion_handlers import _case_request, _headers, _post
        from dev12_completion_operator_handlers import (_census, _operator_client,
                                                         _read, _retained)
        from duranki_server.successor_contract import classify_request
        if (case["scenario_id"], case["variant"], case["id"]) != (
                "t60", "composed", checkpoint["failed_id"] + ".continuation5"):
            raise RuntimeError("unregistered operator-identity continuation case")
        before = _census(self)
        before_campaign = self.allowance.inspect()
        correlated_before = self._correlation_snapshot()
        expected = checkpoint["retained_t60_positive_attempt_ids"]
        positives = {}
        for principal, aid in zip(("user.demo", "svc.vega", "svc.orion"), expected):
            sid, record = correlated_before["submissions"].get(aid, (None, None))
            guard_sid, guard = correlated_before["guards"].get(aid, (None, None))
            usage = correlated_before["latest_usage"].get(aid)
            arrivals = [row for row in correlated_before["receiver_rows"]
                        if row.get("attempt_id") == aid]
            if (record is None or record["work_key"]["principal_id"] != principal or
                    record["work_key"]["step_id"] != "step.completion02.t60.composed" or
                    record["campaign_id"] != self.allowance.campaign_id or
                    record["submission_state"] != "completed" or
                    record["delivery_state"] != "valid" or
                    guard_sid != sid or guard.get("plan_id") !=
                        record["signed_plan"]["plan_id"] or
                    len(arrivals) != 1 or arrivals[0]["body_sha256"] !=
                        guard["body_sha256"] or usage is None or
                    usage[2]["cost_status"] != "calculated"):
                raise RuntimeError("retained T60 positive attempt lineage differs")
            positives[principal] = {"attempt_id": aid, "submission_id": sid,
                "actor_id": record["trusted_identity"]["actor_id"],
                "initiating_user_id": record["request"]["metadata"].get(
                    "initiating_user_id"),
                "delegation": record["request"]["metadata"].get("delegation", []),
                "cost_status": usage[2]["cost_status"],
                "receiver_arrivals": len(arrivals)}
        delegated = _case_request(self, case, "DELEGATED_RERANK")
        forged_agent = deepcopy(delegated)
        forged_agent["work_selector"]["step_id"] += ".forged.agent"
        forged_agent["metadata"]["run_id"] = "run.forged.agent"
        forged_owner = deepcopy(delegated)
        forged_owner["work_selector"]["step_id"] += ".forged.owner"
        forged_owner["charging_owner_id"] = "team.forged"
        forged_delegation = deepcopy(delegated)
        forged_delegation["work_selector"]["step_id"] += ".forged.delegation"
        forged_delegation["metadata"]["delegation"][-1]["to_actor_id"] = "agent.forged"
        cyclic = deepcopy(delegated)
        cyclic["work_selector"]["step_id"] += ".cycle"
        cyclic["metadata"]["delegation"][-1]["to_actor_id"] = "user.demo"
        context = self.contexts_by_credential[self.credentials["DELEGATED_RERANK"]]
        negatives_requests = (forged_agent, forged_owner, forged_delegation, cyclic)
        classifications = [classify_request(value, context)
                           for value in negatives_requests]
        if classifications != ["SEMANTIC_INVALID", "SCHEMA_INVALID",
                                "SEMANTIC_INVALID", "SEMANTIC_INVALID"]:
            raise RuntimeError("T60 negative preflight became eligible")
        negatives = [_post(self, value, _headers(self, "DELEGATED_RERANK"))
                     for value in negatives_requests]
        with _operator_client(self) as client:
            report_result = _read(client)
        rows = report_result.get("report", {}).get("attempts", [])
        selected = {row.get("attempt_id"): row for row in rows
                    if row.get("attempt_id") in expected}
        after = _census(self)
        after_campaign = self.allowance.inspect()
        correlated_after = self._correlation_snapshot()
        no_send = (before == after and before_campaign == after_campaign ==
            checkpoint["last_campaign"] and correlated_before == correlated_after and
            before_campaign["attempt_count"] ==
                before_campaign["possible_send_count"] == 76 and
            before_campaign["cumulative_reserved_decimal"] == "0.020400018" and
            len(correlated_before["receiver_rows"]) == 65)
        report_ok = (report_result.get("status") == 200 and len(selected) == 3 and
            all(selected[aid].get("actor_id") == positives[principal]["actor_id"]
                for principal, aid in zip(("user.demo", "svc.vega", "svc.orion"), expected)))
        direct = selected.get(expected[0], {})
        delegated_row = selected.get(expected[1], {})
        autonomous = selected.get(expected[2], {})
        checks = {
            "t60.direct_human": (bool(no_send and report_ok and
                direct.get("actor_id") == "user.demo" and
                direct.get("initiating_user_id") == "user.demo"),
                "Retained direct human attempt appears under its own actor and initiator"),
            "t60.delegated_agent": (bool(no_send and report_ok and
                delegated_row.get("actor_id") == "agent.vega" and
                delegated_row.get("initiating_user_id") == "user.demo" and
                delegated_row.get("parent_run_id") == "run.bud"),
                "Retained delegated agent has the human initiator and immediate parent run"),
            "t60.autonomous": (bool(no_send and report_ok and
                autonomous.get("actor_id") == "svc.orion" and
                autonomous.get("initiating_user_id") is None),
                "Retained autonomous actor has no fabricated initiating human"),
            "t60.forged_agent": (bool(no_send and classifications[0] ==
                "SEMANTIC_INVALID" and negatives[0]["http_status"] >= 400),
                "Forged agent run was rejected without admission or receiver work"),
            "t60.forged_owner": (bool(no_send and classifications[1] ==
                "SCHEMA_INVALID" and negatives[1]["http_status"] >= 400),
                "Caller-supplied owner was rejected before admission"),
            "t60.forged_delegation": (bool(no_send and classifications[2] ==
                "SEMANTIC_INVALID" and negatives[2]["http_status"] >= 400),
                "Forged final delegation endpoint was rejected before admission"),
            "t60.cycle": (bool(no_send and classifications[3] ==
                "SEMANTIC_INVALID" and negatives[3]["http_status"] >= 400),
                "Cyclic delegation was rejected without another receiver arrival")}
        stages = {"operator": {"report_attempts": len(rows),
            "selected_attempts": list(expected),
            "negative_http": [value["http_status"] for value in negatives]}}
        result = _retained(self, case, stages, checks,
            {"continuation_of_case_id": checkpoint["latest_failed_id"],
             "retained_positive_attempts": positives,
             "selected_operator_rows": [direct, delegated_row, autonomous],
             "negative_classifications": classifications,
             "negative_http": [value["http_status"] for value in negatives],
             "campaign_before": before_campaign, "campaign_after": after_campaign,
             "receiver_arrivals_before": len(correlated_before["receiver_rows"]),
             "receiver_arrivals_after": len(correlated_after["receiver_rows"]),
             "new_admissions": 0, "new_possible_sends": 0})
        actual = {"primary_attempt_id": None, "terminal_status": "completed",
            "rejection": None, "primary_stages": [],
            "reservation_delta_decimal": "0.000000000",
            "receiver_attempt_ids": [], "new_attempt_ids": [],
            "new_guard_attempt_ids": [], "new_usage_revisions": [],
            "effective_known_delta_decimal": "0.000000000"}
        return result, actual

    def run_case(self, case: dict, *, continuation_checkpoint: dict | None = None) -> dict:
        from dev12_completion_preflight import verify_case_result
        registration = self.handlers[case["handler"]]
        if continuation_checkpoint is not None and case["scenario_id"] == "t62_e":
            self._ensure_continuation_other_credential()
        if case["scenario_id"] in {"t64", "t65"}:
            name = ("operator-browser-evidence.json" if case["scenario_id"] == "t64"
                    else "preview-browser-evidence.json")
            requested = self.root / name
            append_durable(self.journal, {"kind": "browser_capture_requested",
                "at": time.time_ns(), "case_id": case["id"],
                "operator_url": self.operator_url,
                "source_tree": self.plan["source_tree"],
                "campaign_id": self.plan["envelope"]["campaign_id"],
                "expected_evidence_path": str(requested),
                "wait_limit_seconds": 300})
            deadline = time.monotonic() + 300
            while not requested.is_file() and time.monotonic() < deadline:
                time.sleep(.5)
            if not requested.is_file():
                raise TimeoutError("independent local browser attestation deadline; no send")
        before = self.allowance.inspect()
        correlated_before = self._correlation_snapshot()
        arrivals_before = len(self.receiver_log.read_bytes().splitlines()) if self.receiver_log.exists() else 0
        identity = {"scenario_id": case["scenario_id"], "variant": case["variant"],
                    "case_id": case["id"], "handler": case["handler"],
                    "handler_source_sha256": case["handler_source_sha256"]}
        append_durable(self.journal, {"kind": "case_begin", "at": time.time_ns(),
                                     **identity, "campaign_before": before,
                                     "receiver_arrivals_before": arrivals_before})
        try:
            repair = (continuation_checkpoint is not None and
                      continuation_checkpoint["continuation_number"] <= 5 and
                      case["id"] == continuation_checkpoint["failed_id"] +
                        ".continuation" + str(continuation_checkpoint["continuation_number"]))
            if repair:
                if continuation_checkpoint["continuation_number"] == 1:
                    result, repair_actual = self._repair_partial_write(case,
                        continuation_checkpoint)
                elif continuation_checkpoint["continuation_number"] == 2:
                    result, repair_actual = self._verify_resumed_partial_write(case,
                        continuation_checkpoint)
                elif continuation_checkpoint["continuation_number"] == 3:
                    result, repair_actual = self._verify_installed_client_attempts(case,
                        continuation_checkpoint)
                elif continuation_checkpoint["continuation_number"] == 4:
                    result, repair_actual = self._verify_native_revision_history(case,
                        continuation_checkpoint)
                else:
                    result, repair_actual = self._verify_operator_identity_continuation(case,
                        continuation_checkpoint)
            else:
                result = registration.run(self, case)
            after = self.allowance.inspect()
            correlated_after = self._correlation_snapshot()
            actual = (repair_actual if repair else self._verify_case_correlation(
                case, correlated_before, correlated_after, before, after, result))
            verification = verify_case_result(case, result, self.root,
                                              actual=actual, require_actual=True)
            if verification["status"] != "PASS":
                raise AssertionError("case observations or assertions missing: " +
                                     ", ".join(verification["errors"]))
            arrivals_after = len(self.receiver_log.read_bytes().splitlines()) if self.receiver_log.exists() else 0
            if (after["attempt_count"] - before["attempt_count"] > case["max_admissions"] or
                after["possible_send_count"] - before["possible_send_count"] >
                    case["max_possible_sends"] or
                arrivals_after - arrivals_before > case["max_possible_sends"]):
                raise AssertionError("case exceeded declared resource bounds")
            record = {"kind": "case_end", "at": time.time_ns(), **identity,
                      "status": "PASS", "result": result,
                      "actual_correlation": actual,
                      "verification": verification,
                      "campaign_after": after,
                      "receiver_arrivals_after": arrivals_after}
            append_durable(self.journal, record)
            return record
        except BaseException as exc:
            append_durable(self.journal, {"kind": "case_end", "at": time.time_ns(),
                **identity, "status": "FAIL", "error_type": type(exc).__name__,
                "error": str(exc)[:1000], "campaign_after": self.allowance.inspect(),
                "receiver_arrivals_after":
                    len(self.receiver_log.read_bytes().splitlines()) if self.receiver_log.exists() else 0})
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("artifact_root")
    parser.add_argument("--build-plan", action="store_true",
                        help="freeze a prospective exact inventory without target release")
    parser.add_argument("--build-continuation", action="store_true",
                        help="freeze one no-send successor plan for a stopped campaign")
    parser.add_argument("--continue-existing", action="store_true",
                        help="reopen the stopped campaign without starting or reseeding it")
    parser.add_argument("--prior-plan", type=Path,
                        help="immutable original plan for continuation evidence")
    parser.add_argument("--receipt-path", type=Path,
                        help="new host preflight receipt for the continuation plan")
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--js-package", type=Path)
    parser.add_argument("--service-image")
    parser.add_argument("--node-image")
    parser.add_argument("--operator-port", type=int)
    parser.add_argument("--campaign-id")
    parser.add_argument("--budget-account-id")
    parser.add_argument("--financial-owner-id")
    parser.add_argument("--release", action="store_true",
                        help="start the already-authorized finite target after preflight")
    args = parser.parse_args(argv)
    root = _checked_artifact_root(args.artifact_root)
    if args.build_plan:
        if args.release or args.plan.resolve() != (root / "plan.json").resolve():
            raise SystemExit("plan build writes only artifact_root/plan.json and cannot release")
        if any(value is None for value in (args.wheel, args.js_package,
                args.service_image, args.node_image, args.operator_port,
                args.campaign_id, args.budget_account_id,
                args.financial_owner_id)):
            raise SystemExit("exact package/image/port and distinct campaign scope args required")
        plan = build_plan(root=root, wheel=args.wheel, js_package=args.js_package,
            service_image=args.service_image, node_image=args.node_image,
            operator_port=args.operator_port, campaign_id=args.campaign_id,
            budget_account_id=args.budget_account_id,
            financial_owner_id=args.financial_owner_id)
        raw = (json.dumps(plan, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()
        with args.plan.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        print(json.dumps({"kind": "dev12_completion02_prospective_inventory",
                          "path": str(args.plan), "sha256": sha256(raw).hexdigest(),
                          "cases": len(plan["cases"]),
                          "source_tree": plan["source_tree"]}, sort_keys=True))
        return
    if args.build_continuation:
        if args.release or args.continue_existing or args.prior_plan is None or \
                args.prior_plan.resolve() != (root / "plan.json").resolve() or \
                args.plan.resolve() == args.prior_plan.resolve() or args.plan.exists() or \
                args.plan.parent.resolve() != root:
            raise SystemExit("continuation plan needs a new file in the same artifact root")
        prior_raw = args.prior_plan.read_bytes()
        prior = json.loads(prior_raw)
        checkpoint = continuation_checkpoint(root, prior, prior_raw)
        expected_plan_path = root / ("plan.continuation" +
            str(checkpoint["continuation_number"]) + ".json")
        if args.plan.resolve() != expected_plan_path.resolve():
            raise SystemExit("continuation plan path differs from exact chain ordinal")
        plan = build_continuation_plan(root=root, prior_plan=prior,
                                       checkpoint=checkpoint)
        raw = (json.dumps(plan, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()
        with args.plan.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        print(json.dumps({"kind": "dev12_completion02_continuation_inventory",
            "path": str(args.plan), "sha256": sha256(raw).hexdigest(),
            "source_tree": plan["source_tree"],
            "original_plan_sha256": checkpoint["original_plan_sha256"],
            "passed_cases": len(checkpoint["passed_ids"]),
            "retry_case": checkpoint["failed_id"] + ".continuation" +
                str(checkpoint["continuation_number"]),
            "cases": len(plan["cases"])}, sort_keys=True))
        return
    plan_bytes = args.plan.read_bytes()
    plan = json.loads(plan_bytes)
    from dev12_completion_handlers import DEV12_CASE_HANDLERS
    if not args.release:
        checked = preflight(plan, root, DEV12_CASE_HANDLERS)
        append_durable(root / "preflight-history.jsonl", {"at": time.time_ns(),
                       "plan_sha256": sha256(plan_bytes).hexdigest(),
                       "result": checked})
        print(json.dumps(checked, sort_keys=True))
        if checked["status"] != "PASS":
            raise SystemExit(2)
        return
    if args.continue_existing and args.prior_plan is None:
        raise SystemExit("continuation requires the immutable original plan")
    if args.continue_existing and args.prior_plan.resolve() != (root / "plan.json").resolve():
        raise SystemExit("continuation must bind artifact_root/plan.json")
    if args.continue_existing and args.receipt_path is None:
        raise SystemExit("continuation requires a distinct new host preflight receipt")
    receipt_path = args.receipt_path or root / "preflight-receipt.json"
    if args.continue_existing:
        receipt_path = receipt_path.resolve(strict=True)
        approved = Path("/Users/larrymitchell/Mach33/Duranki-artifacts").resolve(strict=True)
        if approved not in receipt_path.parents or receipt_path == root / "preflight-receipt.json":
            raise SystemExit("continuation receipt must be a distinct durable artifact")
    checkpoint = None
    if args.continue_existing:
        prior_raw = args.prior_plan.read_bytes()
        prior = json.loads(prior_raw)
        checkpoint = continuation_checkpoint(root, prior, prior_raw)
        expected_receipt = root / ("preflight-receipt-continuation" +
            str(checkpoint["continuation_number"]) + ".json")
        if receipt_path != expected_receipt or args.plan.resolve() != \
                (root / ("plan.continuation" + str(checkpoint["continuation_number"]) +
                         ".json")).resolve():
            raise RuntimeError("continuation plan/receipt path differs from exact chain")
        if (plan["envelope"]["campaign_id"] != prior["envelope"]["campaign_id"] or
                plan["envelope"]["budget_account_id"] != prior["envelope"]["budget_account_id"] or
                plan["envelope"]["financial_owner_id"] != prior["envelope"]["financial_owner_id"] or
                plan["envelope"]["max_admissions"] != prior["envelope"]["max_admissions"] or
                plan["envelope"]["max_possible_sends"] != prior["envelope"]["max_possible_sends"] or
                plan["envelope"]["max_inflight"] != prior["envelope"]["max_inflight"] or
                plan["envelope"]["ceiling_decimal"] != prior["envelope"]["ceiling_decimal"] or
                plan["envelope"]["window_hours"] != prior["envelope"]["window_hours"] or
                plan["envelope"]["preexisting_exposure_decimal"] !=
                    checkpoint["last_campaign"]["cumulative_reserved_decimal"] or
                [(case["scenario_id"], case["variant"]) for case in plan["cases"]] !=
                    [(case["scenario_id"], case["variant"]) for case in prior["cases"]] or
                plan["artifacts"] != prior["artifacts"] or
                plan["cases"][len(checkpoint["passed_ids"])]["id"] !=
                    checkpoint["failed_id"] + ".continuation" +
                        str(checkpoint["continuation_number"])):
            raise RuntimeError("continuation plan changes immutable campaign or case identity")
    elif (root / "campaign.sqlite").exists():
        raise RuntimeError("existing campaign must use explicit continuation")
    receipt = checked_release_receipt(plan_bytes, plan, root, DEV12_CASE_HANDLERS,
                                      receipt_path=receipt_path)
    append_durable(root / "release-gate.jsonl", {"at": time.time_ns(),
                   "preflight_receipt_sha256": sha256(receipt_path.read_bytes()).hexdigest(),
                   "preflight_receipt_path": str(receipt_path),
                   "plan_sha256": receipt["plan_sha256"], "source_tree": receipt["source_tree"],
                   "continuation_of_plan_sha256": checkpoint["original_plan_sha256"]
                       if checkpoint else None})
    runtime = CompletionRuntime(plan, root, DEV12_CASE_HANDLERS)
    try:
        if checkpoint:
            runtime.continue_existing(checkpoint, receipt)
        else:
            runtime.start()
        for case in plan["cases"]:
            if checkpoint and case["id"] in checkpoint["passed_ids"]:
                append_durable(runtime.journal, {"kind": "case_skipped_verified",
                    "at": time.time_ns(), "case_id": case["id"],
                    "original_plan_sha256": checkpoint["original_plan_sha256"],
                    "continuation_plan_sha256": receipt["plan_sha256"]})
                continue
            runtime.run_case(case, continuation_checkpoint=checkpoint)
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
