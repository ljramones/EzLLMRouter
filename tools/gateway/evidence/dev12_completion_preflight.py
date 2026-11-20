"""No-send gate for a prospective, finite DEV-12 target qualification.

This intentionally rejects an incomplete inventory. It has no admission,
sender, receiver, or campaign-start side effects.
"""

from __future__ import annotations

if not __package__:
    import sys
    from pathlib import Path

    for _parent in Path(__file__).resolve().parents:
        if (_parent / "tools/gateway/__init__.py").is_file():
            sys.path.insert(0, str(_parent))
            break
        if (_parent / "server/tools/gateway/__init__.py").is_file():
            sys.path.insert(0, str(_parent / "server"))
            break


from tools.gateway.paths import source_root

from decimal import Decimal, InvalidOperation
from hashlib import sha256
import importlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

from tools.gateway.evidence.dev12_completion_catalog import (
    CaseHandler,
    REQUIRED_PAIRS,
    SCENARIOS,
    SELECTED_IDS,
    ScenarioSpec,
    source_path_for_handler,
)


def selected_ids():
    ids = {
        "T-01",
        "T-02",
        "T-03",
        "T-42",
        "T-60",
        "T-61",
        "T-64",
        "T-65",
        "T-66",
        "T-14.a",
        "T-07.a",
    }
    for parent, letters in (
        ("T-24", "abc"),
        ("T-45", "abcde"),
        ("T-46", "abcd"),
        ("T-47", "abcd"),
        ("T-48", "abcdefg"),
        ("T-49", "abcde"),
        ("T-50", "abcde"),
        ("T-62", "abcde"),
        ("T-77", "abcd"),
        ("T-78", "abcd"),
        ("T-79", "abcd"),
    ):
        ids.update(f"{parent}.{letter}" for letter in letters)
    ids.update(f"T-{number}" for number in range(51, 56))
    return frozenset(ids)


REQUIRED_IDS = selected_ids()
if REQUIRED_IDS != SELECTED_IDS:
    raise RuntimeError("selected assurance labels differ from fixed scenario catalog")
CASE_FIELDS = frozenset(
    {
        "id",
        "assurance_ids",
        "handler",
        "prerequisites",
        "scope",
        "installed_client_mode",
        "fixture",
        "source_tree",
        "build",
        "max_admissions",
        "max_possible_sends",
        "max_exposure_decimal",
        "expected_stages",
        "expected_rejection",
        "late_dependencies",
        "terminal_status",
        "evidence_paths",
        "predicates",
        "evidence_kind",
        "reuse_identity",
        "phase",
        "scenario_id",
        "variant",
        "handler_source_sha256",
        "attempt_group",
    }
)
PHASES = {"normal", "recoverable_pause", "late_evidence", "resume", "terminal"}
STAGES = {
    "ingress",
    "admission",
    "signed_plan",
    "authority",
    "guard",
    "first_write",
    "receiver",
    "delivery",
    "settlement",
    "operator",
    "client",
    "accounting",
    "persistence",
}
CASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}\Z")


def _decimal(value, label):
    if type(value) is not str:
        raise ValueError(f"{label}: decimal string required")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{label}: invalid decimal") from exc
    if not amount.is_finite() or amount < 0 or -amount.as_tuple().exponent > 9:
        raise ValueError(f"{label}: nonfinite, negative, or overprecision")
    return amount


def _hash(path):
    value = sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            value.update(block)
    return value.hexdigest()


def _capture_path_ok(value, root):
    if type(value) is not str or not value:
        return False
    supplied = Path(value)
    path = (supplied if supplied.is_absolute() else root / supplied).resolve()
    if not path.is_relative_to(root) or path == root or path.exists():
        return False
    parent = path.parent
    while parent != root:
        if parent.exists() and (not parent.is_dir() or parent.is_symlink()):
            return False
        parent = parent.parent
    return True


def _fixture_path_for_scenario(scenario):
    root = source_root(__file__)
    if scenario == "t03":
        return root / "tests/development_slice/request.json"
    if scenario.startswith("t48_"):
        return root / "tests/fixtures/contracts/dev12-successor-01/tariffs.json"
    if scenario in {"t49_d", "t51", "t52", "t53", "t54"}:
        return Path(__file__).with_name("dev12_completion_receiver.py")
    return root / "tests/fixtures/contracts/dev12-successor-01/vectors.json"


def mounted_source_identity(root=None):
    """Match the runtime's length-prefixed source fingerprint without imports."""
    root = Path(root or source_root(__file__)).resolve()
    roots = tuple(
        root / name
        for name in (
            "server/src",
            "clients/python/src",
            "clients/js",
            "tools/gateway",
            "tools/synthetic",
            "tools/operator",
            "worker",
            "tests/gateway_integration",
            "tests/operator_console",
            "web",
            "tests/fixtures/contracts/dev12-successor-01",
        )
    )
    fixed = tuple(
        root / name
        for name in ("tests/development_slice/request.json", "tests/tool_cycle/scenarios.json")
    )
    if any(not path.is_file() or path.is_symlink() for path in fixed):
        raise FileNotFoundError("required target fixture missing or linked")
    files = sorted(
        [
            path
            for directory in roots
            for path in directory.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix in (".py", ".cjs", ".json", ".md", ".js", ".css", ".html")
        ]
        + list(fixed)
    )
    value = sha256()
    for path in files:
        name = str(path.relative_to(root)).encode()
        contents = path.read_bytes()
        value.update(len(name).to_bytes(4, "big") + name)
        value.update(len(contents).to_bytes(8, "big") + contents)
    return {"sha256": value.hexdigest(), "file_count": len(files)}


_RECOVERY_ORDER = (
    "unknown_pause",
    "retained_receipt",
    "authorized_late_append",
    "denied_resume",
    "eligible_resume",
)


def _validate_recovery_chain(by_id, errors):
    """Require a real, same-attempt, same-scope no-repeat recovery sequence."""
    chain = {}
    for case in by_id.values():
        if case.get("scenario_id") == "recovery_chain":
            chain[case.get("variant")] = case
    if set(chain) != set(_RECOVERY_ORDER):
        errors.append("required recoverable unknown/receipt/append/denied/eligible chain absent")
        return
    scope = chain["unknown_pause"].get("scope")
    attempt_group = chain["unknown_pause"].get("attempt_group")
    if not isinstance(attempt_group, str) or not attempt_group:
        errors.append("recovery chain lacks durable same-attempt identity")
    for index, variant in enumerate(_RECOVERY_ORDER):
        case = chain[variant]
        if case.get("scope") != scope or case.get("attempt_group") != attempt_group:
            errors.append(f"{case['id']}: recovery chain changes scope or attempt")
        if index:
            predecessor = chain[_RECOVERY_ORDER[index - 1]]["id"]
            dependencies = set(case.get("prerequisites", ())) | set(
                case.get("late_dependencies", ())
            )
            if predecessor not in dependencies:
                errors.append(f"{case['id']}: recovery chain lacks {predecessor} dependency")
        if variant == "unknown_pause" and (
            case.get("max_possible_sends") != 1 or case.get("max_admissions") != 1
        ):
            errors.append(f"{case['id']}: recoverable unknown requires one original attempt")
        if variant != "unknown_pause" and (
            case.get("max_possible_sends") != 0 or case.get("max_admissions") != 0
        ):
            errors.append(f"{case['id']}: late evidence or resume may not resend")
    for variant in ("retained_receipt", "authorized_late_append"):
        if chain[variant].get("evidence_kind") != "new":
            errors.append(f"{chain[variant]['id']}: independently retained evidence required")
    for variant in ("denied_resume", "eligible_resume"):
        case = chain[variant]
        if (
            not case.get("late_dependencies")
            or chain["authorized_late_append"]["id"] not in case["late_dependencies"]
        ):
            errors.append(f"{case['id']}: audited resume lacks actual late append")


def _validate_reporting_dependencies(cases, errors):
    """Bind read-only reporting claims to their populated target predecessors."""
    by_pair = {
        (case.get("scenario_id"), case.get("variant")): case for case in cases if type(case) is dict
    }
    required = {
        ("t61", "composed"): (("t60", "composed"), ("recovery_chain", "authorized_late_append")),
        ("t62_a", "composed"): (("t60", "composed"),),
        ("t62_b", "composed"): (("recovery_chain", "authorized_late_append"),),
        ("t62_c", "composed"): (("t60", "composed"),),
        ("t62_d", "composed"): (("t60", "composed"),),
        ("t62_e", "composed"): (("t60", "composed"),),
        ("t64", "composed"): (
            ("t61", "composed"),
            ("t62_a", "composed"),
            ("t62_b", "composed"),
            ("t62_c", "composed"),
            ("t62_d", "composed"),
            ("t62_e", "composed"),
        ),
        ("t65", "composed"): (("t64", "composed"),),
    }
    for pair, dependencies in required.items():
        case = by_pair.get(pair)
        if case is None:
            continue
        prerequisites = case.get("prerequisites")
        if type(prerequisites) is not list:
            errors.append(f"{case.get('id')}: reporting prerequisites must be an explicit list")
            continue
        for predecessor_pair in dependencies:
            predecessor = by_pair.get(predecessor_pair)
            if predecessor is None or predecessor.get("id") not in prerequisites:
                errors.append(
                    f"{case.get('id')}: missing populated reporting prerequisite "
                    f"{predecessor_pair[0]}/{predecessor_pair[1]}"
                )


_PRIMARY_STAGE_ORDER = (
    "ingress",
    "admission",
    "signed_plan",
    "authority",
    "guard",
    "first_write",
    "receiver",
    "delivery",
    "settlement",
)


def _resolved_evidence(path, root):
    if type(path) is not str or not path:
        raise ValueError("empty evidence path")
    supplied = Path(path)
    resolved = (supplied if supplied.is_absolute() else root / supplied).resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError("evidence outside durable root")
    return resolved


def _retained_ref(path, root, retained):
    try:
        return str(_resolved_evidence(path, root)) in retained
    except (OSError, TypeError, ValueError):
        return False


def verify_case_result(
    case, result, artifact_root, *, catalog=SCENARIOS, actual=None, require_actual=False
):
    """Reject a nominal PASS unless every objective has retained observations.

    This verifies the result envelope and evidence identity.  The registered
    handler remains responsible for the case-specific objective comparison;
    the runner must record that source-bound handler identity in its journal.
    """
    errors = []
    if type(result) is not dict or set(result) != {"status", "observations", "assertions"}:
        return {"status": "FAIL", "errors": ["case result shape invalid"]}
    if result["status"] != "PASS":
        errors.append("case handler did not pass")
    observations, assertions = result["observations"], result["assertions"]
    if type(observations) is not list or type(assertions) is not list:
        return {"status": "FAIL", "errors": ["case result rows invalid"]}
    try:
        spec = catalog[case["scenario_id"]].variants[case["variant"]]
    except (KeyError, TypeError):
        return {"status": "FAIL", "errors": ["case scenario/variant invalid"]}
    root = Path(artifact_root).resolve()
    try:
        planned = {_resolved_evidence(path, root) for path in case["evidence_paths"]}
        if len(planned) != len(case["evidence_paths"]) or not planned:
            errors.append("planned evidence paths duplicate or absent")
    except (KeyError, TypeError, ValueError, OSError):
        planned = set()
        errors.append("planned evidence paths invalid")
    retained = set()
    observed_stages = set()
    for row in observations:
        if type(row) is not dict or set(row) != {
            "stage",
            "evidence_path",
            "sha256",
            "case_id",
            "attempt_group",
            "observed",
        }:
            errors.append("observation shape invalid")
            continue
        if row["case_id"] != case["id"] or row["attempt_group"] != case["attempt_group"]:
            errors.append("observation identity differs")
        if row["stage"] not in STAGES or type(row["observed"]) is not dict or not row["observed"]:
            errors.append("observation lacks actual stage values")
        try:
            path = _resolved_evidence(row["evidence_path"], root)
            if (
                path not in planned
                or not path.is_file()
                or path.is_symlink()
                or _hash(path) != row["sha256"]
            ):
                raise ValueError("unretained evidence")
        except (OSError, TypeError, ValueError):
            errors.append("observation evidence missing or changed")
            continue
        retained.add(str(path))
        observed_stages.add(row["stage"])
    if not set(spec.required_stages).issubset(observed_stages):
        errors.append("required stage observations missing")
    if retained != {str(path) for path in planned}:
        errors.append("observations do not bind exact planned evidence paths")
    expected = set(spec.assertion_ids)
    seen = set()
    for row in assertions:
        if type(row) is not dict or set(row) != {
            "id",
            "passed",
            "executed",
            "evidence_paths",
            "detail",
        }:
            errors.append("assertion shape invalid")
            continue
        ident = row["id"]
        if ident in seen or ident not in expected:
            errors.append("duplicate or unregistered objective assertion")
        seen.add(ident)
        if row["passed"] is not True or row["executed"] is not True:
            errors.append("objective assertion failed or unexecuted")
        if (
            type(row["detail"]) is not str
            or row["detail"].strip().lower() in {"", "pass", "passed", "ok", "true", "success"}
            or type(row["evidence_paths"]) is not list
            or not row["evidence_paths"]
            or not all(_retained_ref(path, root, retained) for path in row["evidence_paths"])
        ):
            errors.append("objective assertion lacks retained evidence")
    if seen != expected:
        errors.append("required objective assertions missing")
    if require_actual and actual is None:
        errors.append("independent runtime facts missing")
    if actual is not None:
        if type(actual) is not dict or not {
            "primary_attempt_id",
            "terminal_status",
            "rejection",
            "primary_stages",
            "reservation_delta_decimal",
        }.issubset(actual):
            errors.append("independent runtime facts malformed")
        else:
            try:
                reserved = _decimal(
                    actual["reservation_delta_decimal"], "independent reservation delta"
                )
                allocated = _decimal(case["max_exposure_decimal"], "planned case exposure")
                if reserved > allocated:
                    errors.append("case exceeded planned USD reservation allocation")
            except (KeyError, ValueError) as exc:
                errors.append(str(exc))
            if actual["terminal_status"] != case.get("terminal_status"):
                errors.append("primary terminal state differs from planned state")
            if actual["rejection"] != case.get("expected_rejection"):
                errors.append("primary rejection differs from planned stage/code/status")
            attempt_id = actual["primary_attempt_id"]
            if attempt_id is not None and (type(attempt_id) is not str or not attempt_id):
                errors.append("independent primary attempt identity invalid")
            if case.get("max_admissions", 0) and attempt_id is None:
                errors.append("admitted case lacks independent primary attempt")
            reached = actual["primary_stages"]
            if type(reached) is not list or any(
                stage not in _PRIMARY_STAGE_ORDER for stage in reached
            ):
                errors.append("independent primary stages malformed")
            elif case.get("expected_rejection") is not None:
                rejected_stage = case["expected_rejection"]["stage"]
                if rejected_stage not in _PRIMARY_STAGE_ORDER:
                    errors.append("planned rejection stage unsupported")
                elif rejected_stage != "delivery" and any(
                    _PRIMARY_STAGE_ORDER.index(stage) > _PRIMARY_STAGE_ORDER.index(rejected_stage)
                    for stage in reached
                ):
                    errors.append("primary rejection has forbidden later stage evidence")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors}


def _continuation_context(plan, root, prior_exposure, errors):
    """Bind a continued prospectus to one unchanged durable parent campaign."""
    if prior_exposure == 0:
        if (root / "campaign.sqlite").exists():
            errors.append("existing durable campaign requires checked continuation")
        return None
    try:
        from tools.gateway.evidence.dev12_completion_runner import continuation_checkpoint

        prior_path = root / "plan.json"
        database = root / "campaign.sqlite"
        if (
            not prior_path.is_file()
            or prior_path.is_symlink()
            or not database.is_file()
            or database.is_symlink()
        ):
            raise ValueError("original plan or campaign database absent")
        prior_bytes = prior_path.read_bytes()
        prior = json.loads(prior_bytes)
        checkpoint = continuation_checkpoint(root, prior, prior_bytes)
        old, new = prior["envelope"], plan["envelope"]
        if (
            plan["artifacts"] != prior["artifacts"]
            or {key: value for key, value in new.items() if key != "preexisting_exposure_decimal"}
            != {key: value for key, value in old.items() if key != "preexisting_exposure_decimal"}
            or old["preexisting_exposure_decimal"] != "0.000000000"
            or len(plan["cases"]) != len(prior["cases"])
        ):
            raise ValueError("continuation changes original inputs or allowance")
        passed = set(checkpoint["passed_ids"])
        failed = checkpoint["failed_id"]
        latest_failed = checkpoint.get("latest_failed_id", failed)
        continuation_number = checkpoint.get("continuation_number")
        if continuation_number is None:
            continuation_number = (
                2
                if latest_failed == failed + ".continuation1"
                else 1
                if latest_failed == failed
                else 0
            )
        if continuation_number not in (1, 2, 3, 4, 5, 6, 7, 8):
            raise ValueError("unsupported or skipped continuation checkpoint")
        if (
            continuation_number == 1
            and latest_failed != failed
            or continuation_number == 2
            and latest_failed != failed + ".continuation1"
            or continuation_number == 3
            and (failed != "case.t47_a.composed" or latest_failed != failed)
            or continuation_number == 4
            and (failed != "case.t49_d.composed" or latest_failed != failed)
            or continuation_number == 5
            and (failed != "case.t60.composed" or latest_failed != failed)
            or continuation_number == 6
            and (failed != "case.t62_b.composed" or latest_failed != failed)
            or continuation_number == 7
            and (failed != "case.t62_e.composed" or latest_failed != failed)
            or continuation_number == 8
            and (failed != "case.t64.composed" or latest_failed != failed)
        ):
            raise ValueError("continuation failed case identity differs")
        previous = prior
        for previous_number in range(1, continuation_number):
            previous_path = root / ("plan.continuation" + str(previous_number) + ".json")
            previous_receipt_path = root / (
                "preflight-receipt-continuation" + str(previous_number) + ".json"
            )
            if (
                not previous_path.is_file()
                or previous_path.is_symlink()
                or not previous_receipt_path.is_file()
                or previous_receipt_path.is_symlink()
            ):
                raise ValueError("prior continuation plan or receipt absent")
            previous_bytes = previous_path.read_bytes()
            previous = json.loads(previous_bytes)
            previous_receipt = json.loads(previous_receipt_path.read_bytes())
            if (
                previous_receipt.get("plan_sha256") != sha256(previous_bytes).hexdigest()
                or previous_receipt.get("source_tree") != previous.get("source_tree")
                or previous_receipt.get("case_count") != len(previous["cases"])
            ):
                raise ValueError("prior continuation receipt differs from exact plan")
        previous_failed = next(
            (case for case in previous["cases"] if case["id"] == latest_failed), None
        )
        if previous_failed is None or (
            continuation_number > 1
            and previous_failed["evidence_paths"] != ["cases/" + latest_failed + ".json"]
        ):
            raise ValueError("prior continuation failed case identity differs")
        previous_evidence = root / previous_failed["evidence_paths"][0]
        if (
            continuation_number > 1
            and continuation_number not in (5, 6, 7, 8)
            and (not previous_evidence.is_file() or previous_evidence.is_symlink())
        ):
            raise ValueError("prior continuation failed evidence absent")
        if continuation_number in (5, 6, 7, 8) and previous_evidence.exists():
            raise ValueError("operator case stopped before original evidence capture")
        if latest_failed in passed or len(passed) + 1 > len(plan["cases"]):
            raise ValueError("continuation checkpoint case census invalid")
        if len(previous["cases"]) != len(prior["cases"]):
            raise ValueError("prior continuation case census differs")
        repair_id = (
            (failed if continuation_number <= 2 else latest_failed)
            + ".continuation"
            + str(continuation_number)
        )
        for current, original, preceding in zip(
            plan["cases"], prior["cases"], previous["cases"], strict=True
        ):
            pair = (
                "scenario_id",
                "variant",
                "scope",
                "attempt_group",
                "assurance_ids",
                "handler",
                "phase",
                "predicates",
                "expected_stages",
                "fixture",
                "installed_client_mode",
            )
            if (
                any(current[key] != original[key] or current[key] != preceding[key] for key in pair)
                or current["prerequisites"]
                != [
                    repair_id if value == latest_failed else value
                    for value in preceding["prerequisites"]
                ]
                or current["late_dependencies"]
                != [
                    repair_id if value == latest_failed else value
                    for value in preceding["late_dependencies"]
                ]
            ):
                raise ValueError("continuation changes selected case identity")
            if preceding["id"] == latest_failed:
                expected_allocation = (0, 0, Decimal(0))
                actual_allocation = (
                    current["max_admissions"],
                    current["max_possible_sends"],
                    _decimal(current["max_exposure_decimal"], "repair exposure"),
                )
                if (
                    current["id"] != repair_id
                    or current["evidence_paths"] != ["cases/" + repair_id + ".json"]
                    or actual_allocation != expected_allocation
                ):
                    raise ValueError("continued failed-case allocation differs")
            elif (
                current["id"] != preceding["id"]
                or current["evidence_paths"] != preceding["evidence_paths"]
            ):
                raise ValueError("continuation changes retained case or evidence identity")
        wal = Path(str(database) + "-wal")
        shm = Path(str(database) + "-shm")
        journal = Path(str(database) + "-journal")
        if (
            journal.exists()
            or wal.exists() != shm.exists()
            or any(path.is_symlink() for path in (wal, shm, journal))
        ):
            raise ValueError("campaign database has an incomplete or unsafe sidecar")
        had_wal = wal.exists()
        inspected = (database, wal) if had_wal else (database,)
        before = {
            path: (
                path.stat().st_size,
                path.stat().st_mtime_ns,
                sha256(path.read_bytes()).hexdigest(),
            )
            for path in inspected
        }
        shm_size = shm.stat().st_size if had_wal else None
        # A stopped WAL-mode database can retain both sidecars. Read the WAL
        # through SQLite's read-only mode; immutable=1 would silently omit it.
        mode = "mode=ro" if had_wal else "immutable=1"
        with sqlite3.connect("file:" + str(database) + "?" + mode, uri=True) as connection:
            rows = connection.execute(
                "SELECT record FROM dev12_campaigns WHERE campaign_id=?", (new["campaign_id"],)
            ).fetchall()
        if (
            any(
                not path.is_file()
                or path.is_symlink()
                or (
                    path.stat().st_size,
                    path.stat().st_mtime_ns,
                    sha256(path.read_bytes()).hexdigest(),
                )
                != before[path]
                for path in inspected
            )
            or wal.exists() != had_wal
            or shm.exists() != had_wal
            or (
                had_wal
                and (not shm.is_file() or shm.is_symlink() or shm.stat().st_size != shm_size)
            )
            or journal.exists()
        ):
            raise ValueError("campaign database or WAL bytes changed during read")
        if len(rows) != 1:
            raise ValueError("original durable campaign record absent")
        durable = json.loads(rows[0][0])
        prior_state = checkpoint["last_campaign"]
        if (
            durable != prior_state
            or durable["start_at"] != checkpoint["original_start_at"]
            or durable["expires_at"] != checkpoint["original_expires_at"]
            or durable["campaign_id"] != new["campaign_id"]
            or durable["budget_account_id"] != new["budget_account_id"]
            or durable["financial_owner_id"] != new["financial_owner_id"]
            or _decimal(durable["cumulative_reserved_decimal"], "durable exposure")
            != prior_exposure
        ):
            raise ValueError("continuation prior exposure or durable counters differ")
        if (
            type(durable["attempt_count"]) is not int
            or type(durable["possible_send_count"]) is not int
            or not 0 <= durable["possible_send_count"] <= durable["attempt_count"] <= 512
        ):
            raise ValueError("continuation prior attempt/send counters invalid")
        if continuation_number == 2 and (
            durable.get("paused") is not False
            or durable["attempt_count"] != 11
            or durable["possible_send_count"] != 11
            or prior_exposure != Decimal("0.002900002")
        ):
            raise ValueError("second continuation changes observed stopped campaign")
        if continuation_number == 3 and (
            durable.get("paused") is not False
            or durable["attempt_count"] != 35
            or durable["possible_send_count"] != 35
            or prior_exposure != Decimal("0.008000003")
            or len(passed) != 25
            or "case.t24_b.partial_write.continuation2" not in passed
        ):
            raise ValueError("third continuation changes observed stopped campaign")
        if continuation_number == 4 and (
            durable.get("paused") is not False
            or durable["attempt_count"] != 51
            or durable["possible_send_count"] != 51
            or prior_exposure != Decimal("0.012200008")
            or len(passed) != 40
            or "case.t47_a.composed.continuation3" not in passed
            or previous_failed["max_possible_sends"] != 3
            or previous_failed["evidence_kind"] != "new"
        ):
            raise ValueError("fourth continuation changes observed stopped campaign")
        if continuation_number == 5 and (
            durable.get("paused") is not False
            or durable["attempt_count"] != 76
            or durable["possible_send_count"] != 76
            or prior_exposure != Decimal("0.020400018")
            or len(passed) != 52
            or "case.t49_d.composed.continuation4" not in passed
            or previous_failed["max_possible_sends"] != 3
            or previous_failed["evidence_kind"] != "new"
        ):
            raise ValueError("fifth continuation changes observed stopped campaign")
        if continuation_number == 6 and (
            durable.get("paused") is not False
            or durable["attempt_count"] != 91
            or durable["possible_send_count"] != 91
            or prior_exposure != Decimal("0.027600030")
            or len(passed) != 74
            or "case.t60.composed.continuation5" not in passed
            or "case.t62_a.composed" not in passed
            or previous_failed["scenario_id"] != "t62_b"
            or previous_failed["variant"] != "composed"
            or checkpoint.get("failed_attempt_ids") != []
            or checkpoint.get("latest_failed_evidence") is not None
        ):
            raise ValueError("sixth continuation changes no-send stopped campaign")
        if continuation_number == 7 and (
            durable.get("paused") is not False
            or durable["attempt_count"] != 91
            or durable["possible_send_count"] != 91
            or prior_exposure != Decimal("0.027600030")
            or len(passed) != 77
            or not {
                "case.t62_b.composed.continuation6",
                "case.t62_c.composed",
                "case.t62_d.composed",
            }.issubset(passed)
            or previous_failed["scenario_id"] != "t62_e"
            or previous_failed["variant"] != "composed"
            or checkpoint.get("failed_attempt_ids") != []
            or checkpoint.get("latest_failed_evidence") is not None
        ):
            raise ValueError("seventh continuation changes no-send stopped campaign")
        if continuation_number == 8 and (
            durable.get("paused") is not False
            or durable["attempt_count"] != 91
            or durable["possible_send_count"] != 91
            or prior_exposure != Decimal("0.027600030")
            or len(passed) != 78
            or "case.t62_e.composed.continuation7" not in passed
            or previous_failed["scenario_id"] != "t64"
            or previous_failed["variant"] != "composed"
            or checkpoint.get("failed_attempt_ids") != []
            or checkpoint.get("latest_failed_evidence") is not None
        ):
            raise ValueError("eighth continuation changes no-send stopped campaign")
        if continuation_number in (7, 8):
            from tools.gateway.evidence.dev12_completion_runner import _journal_rows

            if any(
                row.get("kind") in {"case_begin", "case_end"}
                and row.get("case_id") == latest_failed
                for row in _journal_rows(root / "case-journal.jsonl")
            ):
                raise ValueError("operator capture stop must precede case begin")
        if continuation_number == 4:
            failed_attempts = checkpoint.get("failed_attempt_ids")
            if (
                type(failed_attempts) is not list
                or len(failed_attempts) != 3
                or any(type(value) is not str or not value for value in failed_attempts)
                or len(set(failed_attempts)) != 3
            ):
                raise ValueError("retained T49d three-attempt evidence unavailable")
        if continuation_number in (5, 6, 7, 8):
            positives = checkpoint.get("retained_t60_positive_attempt_ids")
            if (
                (
                    continuation_number == 5
                    and (
                        previous_failed["scenario_id"],
                        previous_failed["variant"],
                        previous_failed["expected_stages"],
                    )
                    != ("t60", "composed", ["operator"])
                )
                or type(positives) is not list
                or len(positives) != 3
                or any(type(value) is not str or not value for value in positives)
                or len(set(positives)) != 3
            ):
                raise ValueError("retained T60 positive attempts are unverified")
        retained_live_clients = set()
        if continuation_number == 3:
            attempts = checkpoint.get("failed_attempt_ids")
            if (
                previous_failed["id"] != "case.t47_a.composed"
                or previous_failed["installed_client_mode"] != "both"
                or previous_failed["evidence_kind"] != "new"
                or previous_failed["max_possible_sends"] != 2
                or type(attempts) is not list
                or len(attempts) != 2
                or any(type(value) is not str or not value for value in attempts)
                or attempts[0] == attempts[1]
            ):
                raise ValueError("retained installed-client submissions are unverified")
            # The checkpoint independently verifies both completed attempts,
            # receiver arrivals, campaign deltas and exact retained T47a evidence.
            retained_live_clients.update(("python_wheel", "js_tarball"))
        if continuation_number in (4, 5, 6, 7, 8):
            attempts = checkpoint.get("retained_t47_live_attempt_ids")
            evidence = checkpoint.get("retained_t47_live_evidence")
            source = root / "cases/case.t47_a.composed.json"
            if (
                type(attempts) is not list
                or len(attempts) != 2
                or any(type(value) is not str or not value for value in attempts)
                or attempts[0] == attempts[1]
                or type(evidence) is not dict
                or set(evidence) != {"path", "sha256", "bytes"}
                or evidence["path"] != str(source)
                or not source.is_file()
                or source.is_symlink()
                or evidence["bytes"] != source.stat().st_size
                or evidence["sha256"] != sha256(source.read_bytes()).hexdigest()
            ):
                raise ValueError("retained installed-client submissions are unverified")
            # The checkpoint proves these two IDs came from actual completed
            # Python and CommonJS sends in this same durable campaign.
            retained_live_clients.update(("python_wheel", "js_tarball"))
        return {
            "checkpoint": checkpoint,
            "prior_plan": prior,
            "prior_attempts": durable["attempt_count"],
            "prior_sends": durable["possible_send_count"],
            "prior_reserved": prior_exposure,
            "passed_ids": passed,
            "retained_live_client_modes": retained_live_clients,
        }
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        sqlite3.Error,
        RuntimeError,
        json.JSONDecodeError,
    ) as exc:
        errors.append("continuation checkpoint unavailable or changed: " + str(exc))
        return None


def validate(
    plan,
    *,
    handlers,
    artifact_root,
    image_ids,
    required_ids=REQUIRED_IDS,
    catalog=SCENARIOS,
    required_pairs=REQUIRED_PAIRS,
    handler_source_path=None,
):
    """Fail closed before a target campaign is started or any request is sent."""
    errors = []
    if type(plan) is not dict or set(plan) != {"envelope", "cases", "artifacts", "source_tree"}:
        raise ValueError("exact plan envelope/cases/artifacts/source_tree required")
    envelope, cases, artifacts = plan["envelope"], plan["cases"], plan["artifacts"]
    if type(envelope) is not dict or type(cases) is not list or type(artifacts) is not list:
        raise ValueError("typed plan sections required")
    if (
        envelope.get("max_admissions") != 512
        or envelope.get("max_possible_sends") != 512
        or envelope.get("max_inflight") != 2
        or envelope.get("ceiling_decimal") != "6.000000000"
        or envelope.get("window_hours") != 24
        or envelope.get("real_provider_calls") != 0
    ):
        errors.append("owner's exact prospective envelope absent")
    for field in ("rerun_headroom_admissions", "rerun_headroom_sends"):
        if type(envelope.get(field)) is not int or envelope[field] < 0:
            errors.append(f"declared {field} absent")
    try:
        rerun_headroom = _decimal(envelope.get("rerun_headroom_decimal"), "rerun headroom")
        prior_exposure = _decimal(
            envelope.get("preexisting_exposure_decimal"), "preexisting exposure"
        )
    except ValueError as exc:
        errors.append(str(exc))
        rerun_headroom = prior_exposure = Decimal("6.000000001")
    if (
        not isinstance(envelope.get("campaign_id"), str)
        or not isinstance(envelope.get("budget_account_id"), str)
        or not isinstance(envelope.get("financial_owner_id"), str)
        or envelope.get("budget_account_id")
        in {"budget.synthetic.dev12", "budget.synthetic.dev12.correction01"}
        or envelope.get("financial_owner_id") in {"team.demo", "team.synthetic.dev12.correction01"}
    ):
        errors.append("distinct durable campaign/account/owner absent")
    if type(plan["source_tree"]) is not str or len(plan["source_tree"]) != 40:
        errors.append("exact source tree absent")
    root_input = Path(artifact_root)
    root = root_input.resolve()
    if not root.is_dir() or root_input.is_symlink():
        errors.append("durable artifact directory unavailable")
    else:
        try:
            probe = root / "preflight-write-probe.json"
            with probe.open("a") as output:
                output.write('{"kind":"dev12_no_send_preflight"}\n')
                output.flush()
        except OSError:
            errors.append("durable artifact directory not exclusively writable")
    continuation = _continuation_context(plan, root, prior_exposure, errors)

    artifact_kinds = set()
    for artifact in artifacts:
        if type(artifact) is not dict or set(artifact) != {"kind", "path", "sha256"}:
            errors.append("incomplete artifact identity")
            continue
        kind, path, digest = artifact["kind"], artifact["path"], artifact["sha256"]
        if kind in artifact_kinds or kind not in {
            "python_wheel",
            "js_tarball",
            "service_image",
            "node_image",
        }:
            errors.append("duplicate/unknown artifact kind")
        artifact_kinds.add(kind)
        if kind.endswith("image"):
            if path not in image_ids or digest != path.removeprefix("sha256:"):
                errors.append(f"{kind}: exact local image unavailable")
        elif not Path(path).is_file() or _hash(path) != digest:
            errors.append(f"{kind}: package bytes differ")
    if artifact_kinds != {"python_wheel", "js_tarball", "service_image", "node_image"}:
        errors.append("both installed packages and both frozen images required")

    by_id = {}
    covered = set()
    covered_pairs = set()
    client_modes = set()
    live_client_modes = set(continuation["retained_live_client_modes"]) if continuation else set()
    handler_identities = {}
    registered_runs = {}
    admissions = continuation["prior_attempts"] if continuation else 0
    sends = continuation["prior_sends"] if continuation else 0
    exposure = continuation["prior_reserved"] if continuation else Decimal(0)
    for case in cases:
        if type(case) is not dict or set(case) != CASE_FIELDS:
            errors.append("case has missing/extra fields")
            continue
        ident = case["id"]
        if type(ident) is not str or CASE_ID.fullmatch(ident) is None or ident in by_id:
            errors.append("duplicate/invalid case ID")
            continue
        by_id[ident] = case
        if (
            type(case["assurance_ids"]) is not list
            or (not case["assurance_ids"] and case["scenario_id"] != "recovery_chain")
            or any(item not in required_ids for item in case["assurance_ids"])
        ):
            errors.append(f"{ident}: invalid assurance IDs")
        else:
            covered.update(case["assurance_ids"])
        pair = (case["scenario_id"], case["variant"])
        scenario = catalog.get(pair[0])
        variant_spec = (
            scenario.variants.get(pair[1]) if isinstance(scenario, ScenarioSpec) else None
        )
        if variant_spec is None or pair not in required_pairs:
            errors.append(f"{ident}: unregistered scenario/variant")
        elif pair in covered_pairs:
            errors.append(f"{ident}: duplicate scenario/variant {pair[0]}/{pair[1]}")
        else:
            covered_pairs.add(pair)
            if (
                case["assurance_ids"] != list(scenario.assurance_ids)
                or case["handler"] != variant_spec.handler
                or case["expected_stages"] != list(variant_spec.required_stages)
                or case["predicates"] != list(variant_spec.assertion_ids)
                or case["phase"] != variant_spec.phase
            ):
                errors.append(f"{ident}: case contract differs from fixed scenario/variant")
        handler = handlers.get(case["handler"]) if type(handlers) is dict else None
        if (
            not isinstance(handler, CaseHandler)
            or handler.name != case["handler"]
            or pair not in handler.supported
        ):
            errors.append(f"{ident}: registered executable handler absent")
        else:
            try:
                allowed_handler_source = Path(
                    handler_source_path or source_path_for_handler(handler.name)
                ).resolve()
                source = Path(handler.source_path).resolve(strict=True)
                run_source = Path(inspect.getsourcefile(handler.run) or "").resolve(strict=True)
                digest = _hash(source)
                if (
                    source != allowed_handler_source
                    or run_source != source
                    or handler.source_sha256 != digest
                    or case["handler_source_sha256"] != digest
                    or not inspect.isfunction(handler.run)
                    or getattr(handler.run, "dev12_placeholder", False)
                ):
                    raise ValueError("source identity mismatch")
                handler_identities[handler.name] = {"path": str(source), "sha256": digest}
                previous = registered_runs.setdefault(id(handler.run), handler.name)
                if previous != handler.name:
                    errors.append(
                        f"{ident}: one nominal function registered for multiple handler families"
                    )
            except (OSError, ValueError, TypeError):
                errors.append(f"{ident}: registered handler source identity mismatch")
        if case["phase"] not in PHASES:
            errors.append(f"{ident}: invalid phase")
        rejection = case["expected_rejection"]
        if (
            case["terminal_status"] not in {"completed", "failed", "unknown", "blocked", "reused"}
            or (case["evidence_kind"] == "new" and case["terminal_status"] == "reused")
            or (case["evidence_kind"] == "reused" and case["terminal_status"] != "reused")
            or (
                rejection is not None
                and (
                    type(rejection) is not dict
                    or set(rejection) != {"stage", "code", "http_status"}
                    or rejection.get("stage") not in _PRIMARY_STAGE_ORDER
                    or type(rejection.get("code")) is not str
                    or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,79}", rejection["code"])
                    or type(rejection.get("http_status")) is not int
                    or not 400 <= rejection["http_status"] <= 599
                )
            )
        ):
            errors.append(f"{ident}: terminal/rejection expectation unavailable")
        if case["installed_client_mode"] not in {
            "python_wheel",
            "js_tarball",
            "both",
            "none",
        } or case["scope"] != envelope.get("campaign_id"):
            errors.append(f"{ident}: unsupported client/scope")
        if case["installed_client_mode"] == "both":
            client_modes.update(("python_wheel", "js_tarball"))
        else:
            client_modes.add(case["installed_client_mode"])
        if case["evidence_kind"] == "new" and case["max_possible_sends"]:
            if case["installed_client_mode"] == "both":
                live_client_modes.update(("python_wheel", "js_tarball"))
            else:
                live_client_modes.add(case["installed_client_mode"])
        if pair[0].startswith("t47_") and case["installed_client_mode"] != "both":
            errors.append(f"{ident}: installed-client parity requires both artifacts")
        for key in (
            "prerequisites",
            "late_dependencies",
            "expected_stages",
            "evidence_paths",
            "predicates",
        ):
            if type(case[key]) is not list:
                errors.append(f"{ident}: {key} must be an explicit list")
        if (
            not case["expected_stages"]
            or set(case["expected_stages"]) - STAGES
            or not case["evidence_paths"]
            or not case["predicates"]
            or not all(type(item) is str and item for item in case["predicates"])
        ):
            errors.append(f"{ident}: objective stage/evidence predicates absent")
        if case["evidence_kind"] == "new":
            if continuation and ident in continuation["passed_ids"]:
                if not case["evidence_paths"] or not all(
                    type(path) is str
                    and _resolved_evidence(path, root).is_file()
                    and not _resolved_evidence(path, root).is_symlink()
                    for path in case["evidence_paths"]
                ):
                    errors.append(f"{ident}: checkpoint-verified passed evidence missing")
            elif not case["evidence_paths"] or not all(
                _capture_path_ok(path, root) for path in case["evidence_paths"]
            ):
                errors.append(f"{ident}: evidence capture path unavailable or outside durable root")
        elif case["evidence_kind"] == "reused":
            if not case["evidence_paths"] or not all(
                type(path) is str
                and (root / path).resolve().is_relative_to(root)
                and (root / path).is_file()
                for path in case["evidence_paths"]
            ):
                errors.append(f"{ident}: reused evidence not retained under durable root")
        for label in ("fixture", "build"):
            ref = case[label]
            if (
                type(ref) is not dict
                or set(ref) != {"path", "sha256"}
                or not Path(ref["path"]).is_file()
                or _hash(ref["path"]) != ref["sha256"]
            ):
                errors.append(f"{ident}: exact {label} bytes unavailable")
        if variant_spec is not None:
            try:
                expected_fixture = _fixture_path_for_scenario(pair[0]).resolve(strict=True)
                supplied_fixture = Path(case["fixture"]["path"]).resolve(strict=True)
                if supplied_fixture != expected_fixture:
                    errors.append(f"{ident}: fixture is not the fixed scenario input")
                if handler is not None and isinstance(handler, CaseHandler):
                    supplied_build = Path(case["build"]["path"]).resolve(strict=True)
                    if (
                        supplied_build != Path(handler.source_path).resolve(strict=True)
                        or case["build"]["sha256"] != case["handler_source_sha256"]
                    ):
                        errors.append(f"{ident}: build does not identify reviewed handler bytes")
            except (KeyError, OSError, TypeError, ValueError):
                errors.append(f"{ident}: fixed fixture/build identity unavailable")
        if case["source_tree"] != plan["source_tree"]:
            errors.append(f"{ident}: source tree differs")
        for field in ("max_admissions", "max_possible_sends"):
            if type(case[field]) is not int or not 0 <= case[field] <= 512:
                errors.append(f"{ident}: invalid {field}")
        if type(case["max_admissions"]) is int and type(case["max_possible_sends"]) is int:
            if not continuation or ident not in continuation["passed_ids"]:
                admissions += case["max_admissions"]
                sends += case["max_possible_sends"]
            if case["max_possible_sends"] > case["max_admissions"]:
                errors.append(f"{ident}: send bound exceeds admissions")
            retained_t60_repair = bool(
                continuation
                and continuation["checkpoint"].get("continuation_number") in (5, 6, 7, 8)
                and pair == ("t60", "composed")
                and ident == "case.t60.composed.continuation5"
                and (
                    continuation["checkpoint"]["continuation_number"] == 5
                    or ident in continuation["passed_ids"]
                )
                and case["evidence_kind"] == "new"
                and case["max_admissions"] == case["max_possible_sends"] == 0
            )
            if (
                variant_spec is not None
                and (
                    case["max_admissions"] < variant_spec.minimum_admissions
                    or case["max_possible_sends"] < variant_spec.minimum_possible_sends
                )
                and not retained_t60_repair
            ):
                errors.append(f"{ident}: case resource bound below fixed scenario minimum")
            imported_historical_underbound = (
                (
                    pair == ("t50_e", "composed")
                    and case["phase"] == "terminal"
                    and case["evidence_kind"] == "new"
                    and case["max_admissions"] == 0
                    and case["max_possible_sends"] == 0
                    and case["expected_stages"] == list(variant_spec.required_stages)
                    and case["predicates"] == list(variant_spec.assertion_ids)
                )
                if variant_spec
                else False
            )
            retained_t49d_repair = bool(
                continuation
                and continuation["checkpoint"].get("continuation_number") in (4, 5, 6, 7, 8)
                and pair == ("t49_d", "composed")
                and ident == "case.t49_d.composed.continuation4"
                and (
                    continuation["checkpoint"]["continuation_number"] == 4
                    or ident in continuation["passed_ids"]
                )
                and case["evidence_kind"] == "new"
                and case["max_admissions"] == case["max_possible_sends"] == 0
            )
            if (
                variant_spec is not None
                and case["evidence_kind"] == "new"
                and "receiver" in variant_spec.required_stages
                and case["phase"] not in {"late_evidence", "resume"}
                and case["max_possible_sends"] < 1
                and not imported_historical_underbound
                and not retained_t49d_repair
            ):
                errors.append(f"{ident}: receiver case lacks a possible-send bound")
        try:
            case_exposure = _decimal(case["max_exposure_decimal"], ident)
            if not continuation or ident not in continuation["passed_ids"]:
                exposure += case_exposure
            if case["max_possible_sends"] and case_exposure == 0:
                errors.append(
                    f"{ident}: positive possible-send bound lacks a finite exposure allocation"
                )
        except ValueError as exc:
            errors.append(str(exc))
        if case["evidence_kind"] == "reused":
            reuse = case["reuse_identity"]
            if (
                variant_spec is None
                or not variant_spec.reuse_permitted
                or type(reuse) is not dict
                or set(reuse) != {"source_commit", "evidence_path", "sha256", "correspondence"}
                or not Path(reuse["evidence_path"]).is_file()
                or _hash(reuse["evidence_path"]) != reuse["sha256"]
                or type(reuse["source_commit"]) is not str
                or len(reuse["source_commit"]) != 40
                or type(reuse["correspondence"]) is not dict
                or set(reuse["correspondence"]) != {"current_inputs", "source_inputs", "reason"}
                or not reuse["correspondence"]["current_inputs"]
                or not reuse["correspondence"]["source_inputs"]
                or not reuse["correspondence"]["reason"]
                or case["max_admissions"]
                or case["max_possible_sends"]
            ):
                errors.append(f"{ident}: reused evidence lacks exact correspondence")
        elif case["evidence_kind"] != "new" or case["reuse_identity"] is not None:
            errors.append(f"{ident}: evidence provenance invalid")
    if covered != required_ids:
        errors.append("assurance coverage incomplete: " + ", ".join(sorted(required_ids - covered)))
    if covered_pairs != required_pairs:
        errors.append(
            "scenario/variant inventory incomplete: "
            + ", ".join(
                f"{scenario}/{variant}"
                for scenario, variant in sorted(required_pairs - covered_pairs)
            )
        )
    if not {"python_wheel", "js_tarball"}.issubset(client_modes):
        errors.append("both installed client modes absent from executable inventory")
    if not {"python_wheel", "js_tarball"}.issubset(live_client_modes):
        errors.append("both installed clients absent from fresh target submissions")
    if (
        admissions + envelope.get("rerun_headroom_admissions", 513) > 512
        or sends + envelope.get("rerun_headroom_sends", 513) > 512
        or exposure + rerun_headroom > Decimal("6.000000000")
    ):
        errors.append("mixed inventory exceeds aggregate admission/send/fictional USD limits")

    visited, visiting = set(), set()
    case_positions = {
        case["id"]: index
        for index, case in enumerate(cases)
        if type(case) is dict and type(case.get("id")) is str
    }

    def visit(ident):
        if ident in visiting:
            errors.append("cyclic prerequisite: " + ident)
            return
        if ident in visited:
            return
        visiting.add(ident)
        for dependency in by_id[ident]["prerequisites"] + by_id[ident]["late_dependencies"]:
            if dependency not in by_id:
                errors.append(f"{ident}: missing prerequisite {dependency}")
            else:
                if case_positions.get(dependency, len(cases)) >= case_positions.get(ident, -1):
                    errors.append(f"{ident}: executable order precedes prerequisite {dependency}")
                visit(dependency)
        visiting.remove(ident)
        visited.add(ident)

    for ident in by_id:
        visit(ident)
    terminal = [case for case in cases if case.get("phase") == "terminal"]
    fresh = [
        case
        for case in cases
        if case.get("evidence_kind") == "new" and case.get("max_possible_sends", 0)
    ]
    recovery = [case for case in cases if case.get("scenario_id") == "recovery_chain"]
    for case in terminal:
        must_precede = {row["id"] for row in fresh + recovery if row["id"] != case["id"]}
        missing = must_precede - set(case["prerequisites"])
        if missing:
            errors.append(f"{case['id']}: terminal pause precedes fresh sends")
    _validate_recovery_chain(by_id, errors)
    _validate_reporting_dependencies(cases, errors)
    return {
        "status": "PASS" if not errors else "BLOCKED_NO_SEND",
        "errors": errors,
        "case_count": len(by_id),
        "covered_ids": sorted(covered),
        "covered_pairs": [list(pair) for pair in sorted(covered_pairs)],
        "handler_identities": handler_identities,
        "max_admissions": admissions,
        "max_possible_sends": sends,
        "max_exposure_decimal": str(exposure),
    }


def main():
    if len(sys.argv) not in (4, 5):
        raise SystemExit(
            "usage: dev12_completion_preflight.py PLAN.json HANDLERS_MODULE ARTIFACT_ROOT [NEW_RECEIPT.json]"
        )
    plan_path = Path(sys.argv[1])
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    root = Path(sys.argv[3]).resolve(strict=True)
    continuation = (
        _decimal(plan["envelope"]["preexisting_exposure_decimal"], "preexisting exposure") != 0
    )
    if continuation != (len(sys.argv) == 5):
        raise SystemExit("continuation needs a distinct explicit receipt path")
    receipt_path = Path(sys.argv[4]) if continuation else root / "preflight-receipt.json"
    suffixes = {
        suffix
        for case in plan.get("cases", [])
        if type(case) is dict and type(case.get("id")) is str
        for suffix in (1, 2, 3, 4, 5, 6, 7, 8)
        if case["id"].endswith(".continuation" + str(suffix))
    }
    expected_receipt_name = (
        ("preflight-receipt-continuation" + str(max(suffixes or {1})) + ".json")
        if continuation
        else "preflight-receipt.json"
    )
    if (
        receipt_path.parent.resolve(strict=True) != root
        or receipt_path.name != expected_receipt_name
        or receipt_path.is_symlink()
    ):
        raise SystemExit("receipt must use the exact new path in the same artifact root")
    source = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], capture_output=True, text=True)
    tracked = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--"], capture_output=True, text=True
    )
    extras = subprocess.run(
        [
            "git",
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            "server/src",
            "clients",
            "tools/gateway",
            "tools/synthetic",
            "tools/operator",
            "worker",
            "tests/gateway_integration",
            "tests/fixtures/contracts/dev12-successor-01",
        ],
        capture_output=True,
        text=True,
    )
    if (
        source.returncode != 0
        or tracked.returncode != 0
        or extras.returncode != 0
        or extras.stdout.strip()
        or source.stdout.strip() != plan.get("source_tree")
    ):
        print(
            json.dumps(
                {
                    "status": "BLOCKED_NO_SEND",
                    "errors": ["mounted tracked source does not match planned committed tree"],
                }
            )
        )
        raise SystemExit(2)
    expected_source = source_path_for_handler()
    spec = importlib.util.find_spec(sys.argv[2])
    if spec is None or spec.origin is None or Path(spec.origin).resolve() != expected_source:
        print(
            json.dumps(
                {
                    "status": "BLOCKED_NO_SEND",
                    "errors": ["handler import does not resolve to reviewed target source"],
                }
            )
        )
        raise SystemExit(2)
    module = importlib.import_module(sys.argv[2])
    handlers = getattr(module, "DEV12_CASE_HANDLERS", {})
    image_ids = set()
    for artifact in plan.get("artifacts", []):
        if artifact.get("kind", "").endswith("image"):
            result = subprocess.run(
                ["docker", "image", "inspect", artifact["path"], "--format", "{{.Id}}"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip() == artifact["path"]:
                image_ids.add(artifact["path"])
    result = validate(plan, handlers=handlers, artifact_root=sys.argv[3], image_ids=image_ids)
    if result["status"] != "PASS":
        print(json.dumps(result, sort_keys=True, indent=2))
        raise SystemExit(2)
    receipt = {
        "kind": "dev12_completion02_no_send_preflight_v1",
        "plan_sha256": sha256(plan_bytes).hexdigest(),
        "source_tree": plan["source_tree"],
        "mounted_source_identity": mounted_source_identity(),
        "image_ids": sorted(image_ids),
        "handler_identities": result["handler_identities"],
        "artifacts": plan["artifacts"],
        "case_count": result["case_count"],
        "covered_ids": result["covered_ids"],
        "covered_pairs": result["covered_pairs"],
        "max_admissions": result["max_admissions"],
        "max_possible_sends": result["max_possible_sends"],
        "max_exposure_decimal": result["max_exposure_decimal"],
    }
    data = (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode()
    try:
        with receipt_path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as caught_error:
        if receipt_path.read_bytes() != data:
            print(
                json.dumps(
                    {"status": "BLOCKED_NO_SEND", "errors": ["existing preflight receipt differs"]}
                )
            )
            raise SystemExit(2) from caught_error
    result["receipt_path"] = str(receipt_path)
    result["receipt_sha256"] = sha256(data).hexdigest()
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
