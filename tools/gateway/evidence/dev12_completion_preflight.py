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


from tools.gateway.paths import source_root as source_root

from decimal import Decimal as Decimal, InvalidOperation as InvalidOperation
from hashlib import sha256 as sha256
import importlib as importlib
import importlib.util
import inspect as inspect
import json as json
import os as os
from pathlib import Path as Path
import re as re
import sqlite3 as sqlite3
import subprocess as subprocess
import sys as sys

from tools.gateway.evidence.dev12_completion_catalog import (
    CaseHandler as CaseHandler,
    REQUIRED_PAIRS as REQUIRED_PAIRS,
    SCENARIOS as SCENARIOS,
    SELECTED_IDS as SELECTED_IDS,
    ScenarioSpec as ScenarioSpec,
    source_path_for_handler as source_path_for_handler,
)


if __name__ == "__main__":
    sys.modules.setdefault(
        "tools.gateway.evidence.dev12_completion_preflight", sys.modules[__name__]
    )


from tools.gateway.evidence import (
    dev12_completion_preflight_validation as _dev12_completion_preflight_validation,
)


selected_ids = _dev12_completion_preflight_validation.selected_ids


REQUIRED_IDS = _dev12_completion_preflight_validation.REQUIRED_IDS
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


_continuation_context = _dev12_completion_preflight_validation._continuation_context


validate = _dev12_completion_preflight_validation.validate


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
