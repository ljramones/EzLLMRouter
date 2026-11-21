"""Finite DEV-12 Completion 02 target runner.

Importing this module is side-effect free.  In particular, the receiver,
campaign and sender are never started by the no-send preflight.  A release
requires an exact committed inventory and an explicit ``--release`` flag.
All retained files live beneath the caller's durable artifact directory.
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

from dataclasses import dataclass as dataclass
from datetime import datetime as datetime, timedelta as timedelta, timezone as timezone
from decimal import Decimal as Decimal
from hashlib import sha256 as sha256
import argparse as argparse
import json as json
import os as os
from pathlib import Path as Path
import socket as socket
import subprocess as subprocess
import sys as sys
import threading as threading
import time as time
import tarfile as tarfile
from typing import Any as Any
import zipfile as zipfile


if __name__ == "__main__":
    sys.modules.setdefault("tools.gateway.evidence.dev12_completion_runner", sys.modules[__name__])


ROOT = source_root(__file__)
HERE = Path(__file__).resolve().parent


from tools.gateway.evidence import dev12_completion_plan as _dev12_completion_plan
from tools.gateway.evidence import dev12_completion_checkpoint as _dev12_completion_checkpoint
from tools.gateway.evidence import dev12_completion_setup as _dev12_completion_setup
from tools.gateway.evidence import dev12_completion_correlation as _dev12_completion_correlation
from tools.gateway.evidence import (
    dev12_completion_write_verification as _dev12_completion_write_verification,
)
from tools.gateway.evidence import (
    dev12_completion_usage_verification as _dev12_completion_usage_verification,
)
from tools.gateway.evidence import (
    dev12_completion_identity_verification as _dev12_completion_identity_verification,
)


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode("utf-8")


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
    return {"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest(), "bytes": size}


def _checked_artifact_root(path: str) -> Path:
    root = Path(path).resolve(strict=True)
    approved = Path("/Users/larrymitchell/Mach33/EzLLMRouter-artifacts").resolve(strict=True)
    if root == approved or approved not in root.parents or root.is_symlink():
        raise ValueError("a dedicated directory under EzLLMRouter-artifacts is required")
    if not root.is_dir() or not os.access(root, os.W_OK):
        raise ValueError("durable evidence directory unavailable")
    return root


def _tree() -> str:
    result = subprocess.run(
        ("git", "rev-parse", "HEAD^{tree}"), cwd=ROOT, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _clean_relevant_source() -> bool:
    paths = (
        "server/src",
        "clients",
        "tools/gateway",
        "tools/synthetic",
        "tools/operator",
        "worker",
        "tests/gateway_integration",
        "tests/operator_console",
        "web",
        "tests/fixtures/contracts/dev12-successor-01",
    )
    changed = subprocess.run(
        ("git", "diff", "--quiet", "HEAD", "--", *paths), cwd=ROOT, check=False
    )
    untracked = subprocess.run(
        ("git", "ls-files", "--others", "--exclude-standard", "--", *paths),
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return changed.returncode == 0 and not untracked.stdout.strip()


def preflight(plan: dict, root: Path, handlers: dict) -> dict:
    """No campaign, listener, worker request, admission or send occurs here."""
    from tools.gateway.evidence.dev12_completion_preflight import validate

    if _tree() != plan.get("source_tree") or not _clean_relevant_source():
        return {
            "status": "BLOCKED_NO_SEND",
            "errors": ["committed source tree or mounted target source differs"],
        }
    image_ids = set()
    for artifact in plan.get("artifacts", []):
        if artifact.get("kind", "").endswith("image"):
            result = subprocess.run(
                ("docker", "image", "inspect", artifact["path"], "--format", "{{.Id}}"),
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip() == artifact["path"]:
                image_ids.add(artifact["path"])
    return validate(plan, handlers=handlers, artifact_root=root, image_ids=image_ids)


def checked_release_receipt(
    plan_bytes: bytes, plan: dict, root: Path, handlers: dict, *, receipt_path: Path | None = None
) -> dict:
    """Verify the separate host no-send gate inside the isolated runtime.

    Docker and Git need not be present inside the service image.  The host
    gate has already checked those identities.  The runtime rechecks every
    mounted package/source byte and exact handler registration before release.
    """
    receipt_path = receipt_path or root / "preflight-receipt.json"
    if not receipt_path.is_file() or receipt_path.is_symlink():
        raise RuntimeError("host no-send preflight receipt absent")
    receipt = json.loads(receipt_path.read_bytes())
    expected = {
        "kind",
        "plan_sha256",
        "source_tree",
        "image_ids",
        "handler_identities",
        "artifacts",
        "case_count",
        "covered_ids",
        "covered_pairs",
        "max_admissions",
        "max_possible_sends",
        "max_exposure_decimal",
        "mounted_source_identity",
    }
    if (
        type(receipt) is not dict
        or set(receipt) != expected
        or receipt["kind"] != "dev12_completion02_no_send_preflight_v1"
        or receipt["plan_sha256"] != sha256(plan_bytes).hexdigest()
        or receipt["source_tree"] != plan["source_tree"]
        or receipt["artifacts"] != plan["artifacts"]
        or receipt["case_count"] != len(plan["cases"])
    ):
        raise RuntimeError("host preflight receipt does not bind this exact plan")
    source_identities = receipt["handler_identities"]
    from tools.gateway.evidence.dev12_completion_preflight import mounted_source_identity

    if mounted_source_identity() != receipt["mounted_source_identity"]:
        raise RuntimeError("mounted runtime source differs from host preflight")
    for name, identity in source_identities.items():
        registration = handlers.get(name)
        if (
            registration is None
            or Path(registration.source_path).name != Path(identity.get("path", "")).name
            or registration.source_sha256 != identity.get("sha256")
            or sha256(Path(registration.source_path).read_bytes()).hexdigest()
            != identity.get("sha256")
        ):
            raise RuntimeError("registered handler differs from host-reviewed source")
    for artifact in receipt["artifacts"]:
        if artifact["kind"] in {"python_wheel", "js_tarball"}:
            path = Path(artifact["path"])
            if (
                not path.is_file()
                or path.is_symlink()
                or sha256(path.read_bytes()).hexdigest() != artifact["sha256"]
            ):
                raise RuntimeError("installed-client package differs from host preflight")
        elif artifact["path"] not in receipt["image_ids"]:
            raise RuntimeError("frozen image not in host preflight receipt")
        elif os.environ.get("DEV12_" + artifact["kind"].upper() + "_ID") != artifact["path"]:
            raise RuntimeError("running target image identity declaration differs")
    return receipt


build_plan = _dev12_completion_plan.build_plan


_journal_rows = _dev12_completion_checkpoint._journal_rows


continuation_checkpoint = _dev12_completion_checkpoint.continuation_checkpoint


build_continuation_plan = _dev12_completion_plan.build_continuation_plan


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

    _wait_port = _dev12_completion_setup._wait_port

    _operator_port = _dev12_completion_setup._operator_port

    _bind_contexts = _dev12_completion_setup._bind_contexts

    persist_signer = _dev12_completion_setup.persist_signer

    _ensure_continuation_other_credential = (
        _dev12_completion_setup._ensure_continuation_other_credential
    )

    _install_exact_clients = _dev12_completion_setup._install_exact_clients

    start = _dev12_completion_setup.start

    continue_existing = _dev12_completion_setup.continue_existing

    close = _dev12_completion_setup.close

    restart_service = _dev12_completion_setup.restart_service

    _correlation_snapshot = _dev12_completion_correlation._correlation_snapshot

    _verify_case_correlation = _dev12_completion_correlation._verify_case_correlation

    _repair_partial_write = _dev12_completion_write_verification._repair_partial_write

    _verify_resumed_partial_write = (
        _dev12_completion_write_verification._verify_resumed_partial_write
    )

    _verify_installed_client_attempts = (
        _dev12_completion_usage_verification._verify_installed_client_attempts
    )

    _verify_native_revision_history = (
        _dev12_completion_usage_verification._verify_native_revision_history
    )

    _verify_operator_identity_continuation = (
        _dev12_completion_identity_verification._verify_operator_identity_continuation
    )

    def run_case(self, case: dict, *, continuation_checkpoint: dict | None = None) -> dict:
        from tools.gateway.evidence.dev12_completion_preflight import verify_case_result

        registration = self.handlers[case["handler"]]
        if continuation_checkpoint is not None and case["scenario_id"] == "t62_e":
            self._ensure_continuation_other_credential()
        if case["scenario_id"] in {"t64", "t65"}:
            name = (
                "operator-browser-evidence.json"
                if case["scenario_id"] == "t64"
                else "preview-browser-evidence.json"
            )
            requested = self.root / name
            append_durable(
                self.journal,
                {
                    "kind": "browser_capture_requested",
                    "at": time.time_ns(),
                    "case_id": case["id"],
                    "operator_url": self.operator_url,
                    "source_tree": self.plan["source_tree"],
                    "campaign_id": self.plan["envelope"]["campaign_id"],
                    "expected_evidence_path": str(requested),
                    "wait_limit_seconds": 300,
                },
            )
            deadline = time.monotonic() + 300
            while not requested.is_file() and time.monotonic() < deadline:
                time.sleep(0.5)
            if not requested.is_file():
                raise TimeoutError("independent local browser attestation deadline; no send")
        before = self.allowance.inspect()
        correlated_before = self._correlation_snapshot()
        arrivals_before = (
            len(self.receiver_log.read_bytes().splitlines()) if self.receiver_log.exists() else 0
        )
        identity = {
            "scenario_id": case["scenario_id"],
            "variant": case["variant"],
            "case_id": case["id"],
            "handler": case["handler"],
            "handler_source_sha256": case["handler_source_sha256"],
        }
        append_durable(
            self.journal,
            {
                "kind": "case_begin",
                "at": time.time_ns(),
                **identity,
                "campaign_before": before,
                "receiver_arrivals_before": arrivals_before,
            },
        )
        try:
            repair = (
                continuation_checkpoint is not None
                and continuation_checkpoint["continuation_number"] <= 5
                and case["id"]
                == continuation_checkpoint["failed_id"]
                + ".continuation"
                + str(continuation_checkpoint["continuation_number"])
            )
            if repair:
                if continuation_checkpoint["continuation_number"] == 1:
                    result, repair_actual = self._repair_partial_write(
                        case, continuation_checkpoint
                    )
                elif continuation_checkpoint["continuation_number"] == 2:
                    result, repair_actual = self._verify_resumed_partial_write(
                        case, continuation_checkpoint
                    )
                elif continuation_checkpoint["continuation_number"] == 3:
                    result, repair_actual = self._verify_installed_client_attempts(
                        case, continuation_checkpoint
                    )
                elif continuation_checkpoint["continuation_number"] == 4:
                    result, repair_actual = self._verify_native_revision_history(
                        case, continuation_checkpoint
                    )
                else:
                    result, repair_actual = self._verify_operator_identity_continuation(
                        case, continuation_checkpoint
                    )
            else:
                result = registration.run(self, case)
            after = self.allowance.inspect()
            correlated_after = self._correlation_snapshot()
            actual = (
                repair_actual
                if repair
                else self._verify_case_correlation(
                    case, correlated_before, correlated_after, before, after, result
                )
            )
            verification = verify_case_result(
                case, result, self.root, actual=actual, require_actual=True
            )
            if verification["status"] != "PASS":
                raise AssertionError(
                    "case observations or assertions missing: " + ", ".join(verification["errors"])
                )
            arrivals_after = (
                len(self.receiver_log.read_bytes().splitlines())
                if self.receiver_log.exists()
                else 0
            )
            if (
                after["attempt_count"] - before["attempt_count"] > case["max_admissions"]
                or after["possible_send_count"] - before["possible_send_count"]
                > case["max_possible_sends"]
                or arrivals_after - arrivals_before > case["max_possible_sends"]
            ):
                raise AssertionError("case exceeded declared resource bounds")
            record = {
                "kind": "case_end",
                "at": time.time_ns(),
                **identity,
                "status": "PASS",
                "result": result,
                "actual_correlation": actual,
                "verification": verification,
                "campaign_after": after,
                "receiver_arrivals_after": arrivals_after,
            }
            append_durable(self.journal, record)
            return record
        except BaseException as exc:
            append_durable(
                self.journal,
                {
                    "kind": "case_end",
                    "at": time.time_ns(),
                    **identity,
                    "status": "FAIL",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:1000],
                    "campaign_after": self.allowance.inspect(),
                    "receiver_arrivals_after": len(self.receiver_log.read_bytes().splitlines())
                    if self.receiver_log.exists()
                    else 0,
                },
            )
            raise


def main(argv=None):
    args = _completion_arguments(argv)
    root = _checked_artifact_root(args.artifact_root)
    if args.build_plan:
        if args.release or args.plan.resolve() != (root / "plan.json").resolve():
            raise SystemExit("plan build writes only artifact_root/plan.json and cannot release")
        if any(
            value is None
            for value in (
                args.wheel,
                args.js_package,
                args.service_image,
                args.node_image,
                args.operator_port,
                args.campaign_id,
                args.budget_account_id,
                args.financial_owner_id,
            )
        ):
            raise SystemExit("exact package/image/port and distinct campaign scope args required")
        plan = build_plan(
            root=root,
            wheel=args.wheel,
            js_package=args.js_package,
            service_image=args.service_image,
            node_image=args.node_image,
            operator_port=args.operator_port,
            campaign_id=args.campaign_id,
            budget_account_id=args.budget_account_id,
            financial_owner_id=args.financial_owner_id,
        )
        raw = (json.dumps(plan, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()
        with args.plan.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        print(
            json.dumps(
                {
                    "kind": "dev12_completion02_prospective_inventory",
                    "path": str(args.plan),
                    "sha256": sha256(raw).hexdigest(),
                    "cases": len(plan["cases"]),
                    "source_tree": plan["source_tree"],
                },
                sort_keys=True,
            )
        )
        return
    if args.build_continuation:
        if (
            args.release
            or args.continue_existing
            or args.prior_plan is None
            or args.prior_plan.resolve() != (root / "plan.json").resolve()
            or args.plan.resolve() == args.prior_plan.resolve()
            or args.plan.exists()
            or args.plan.parent.resolve() != root
        ):
            raise SystemExit("continuation plan needs a new file in the same artifact root")
        prior_raw = args.prior_plan.read_bytes()
        prior = json.loads(prior_raw)
        checkpoint = continuation_checkpoint(root, prior, prior_raw)
        expected_plan_path = root / (
            "plan.continuation" + str(checkpoint["continuation_number"]) + ".json"
        )
        if args.plan.resolve() != expected_plan_path.resolve():
            raise SystemExit("continuation plan path differs from exact chain ordinal")
        plan = build_continuation_plan(root=root, prior_plan=prior, checkpoint=checkpoint)
        raw = (json.dumps(plan, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()
        with args.plan.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        print(
            json.dumps(
                {
                    "kind": "dev12_completion02_continuation_inventory",
                    "path": str(args.plan),
                    "sha256": sha256(raw).hexdigest(),
                    "source_tree": plan["source_tree"],
                    "original_plan_sha256": checkpoint["original_plan_sha256"],
                    "passed_cases": len(checkpoint["passed_ids"]),
                    "retry_case": checkpoint["failed_id"]
                    + ".continuation"
                    + str(checkpoint["continuation_number"]),
                    "cases": len(plan["cases"]),
                },
                sort_keys=True,
            )
        )
        return
    plan_bytes = args.plan.read_bytes()
    plan = json.loads(plan_bytes)
    from tools.gateway.evidence.dev12_completion_handlers import DEV12_CASE_HANDLERS

    if not args.release:
        checked = preflight(plan, root, DEV12_CASE_HANDLERS)
        append_durable(
            root / "preflight-history.jsonl",
            {
                "at": time.time_ns(),
                "plan_sha256": sha256(plan_bytes).hexdigest(),
                "result": checked,
            },
        )
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
        approved = Path("/Users/larrymitchell/Mach33/EzLLMRouter-artifacts").resolve(strict=True)
        if approved not in receipt_path.parents or receipt_path == root / "preflight-receipt.json":
            raise SystemExit("continuation receipt must be a distinct durable artifact")
    checkpoint = None
    if args.continue_existing:
        prior_raw = args.prior_plan.read_bytes()
        prior = json.loads(prior_raw)
        checkpoint = continuation_checkpoint(root, prior, prior_raw)
        expected_receipt = root / (
            "preflight-receipt-continuation" + str(checkpoint["continuation_number"]) + ".json"
        )
        if (
            receipt_path != expected_receipt
            or args.plan.resolve()
            != (
                root / ("plan.continuation" + str(checkpoint["continuation_number"]) + ".json")
            ).resolve()
        ):
            raise RuntimeError("continuation plan/receipt path differs from exact chain")
        if (
            plan["envelope"]["campaign_id"] != prior["envelope"]["campaign_id"]
            or plan["envelope"]["budget_account_id"] != prior["envelope"]["budget_account_id"]
            or plan["envelope"]["financial_owner_id"] != prior["envelope"]["financial_owner_id"]
            or plan["envelope"]["max_admissions"] != prior["envelope"]["max_admissions"]
            or plan["envelope"]["max_possible_sends"] != prior["envelope"]["max_possible_sends"]
            or plan["envelope"]["max_inflight"] != prior["envelope"]["max_inflight"]
            or plan["envelope"]["ceiling_decimal"] != prior["envelope"]["ceiling_decimal"]
            or plan["envelope"]["window_hours"] != prior["envelope"]["window_hours"]
            or plan["envelope"]["preexisting_exposure_decimal"]
            != checkpoint["last_campaign"]["cumulative_reserved_decimal"]
            or [(case["scenario_id"], case["variant"]) for case in plan["cases"]]
            != [(case["scenario_id"], case["variant"]) for case in prior["cases"]]
            or plan["artifacts"] != prior["artifacts"]
            or plan["cases"][len(checkpoint["passed_ids"])]["id"]
            != checkpoint["failed_id"] + ".continuation" + str(checkpoint["continuation_number"])
        ):
            raise RuntimeError("continuation plan changes immutable campaign or case identity")
    elif (root / "campaign.sqlite").exists():
        raise RuntimeError("existing campaign must use explicit continuation")
    receipt = checked_release_receipt(
        plan_bytes, plan, root, DEV12_CASE_HANDLERS, receipt_path=receipt_path
    )
    append_durable(
        root / "release-gate.jsonl",
        {
            "at": time.time_ns(),
            "preflight_receipt_sha256": sha256(receipt_path.read_bytes()).hexdigest(),
            "preflight_receipt_path": str(receipt_path),
            "plan_sha256": receipt["plan_sha256"],
            "source_tree": receipt["source_tree"],
            "continuation_of_plan_sha256": checkpoint["original_plan_sha256"]
            if checkpoint
            else None,
        },
    )
    runtime = CompletionRuntime(plan, root, DEV12_CASE_HANDLERS)
    try:
        if checkpoint:
            runtime.continue_existing(checkpoint, receipt)
        else:
            runtime.start()
        for case in plan["cases"]:
            if checkpoint and case["id"] in checkpoint["passed_ids"]:
                append_durable(
                    runtime.journal,
                    {
                        "kind": "case_skipped_verified",
                        "at": time.time_ns(),
                        "case_id": case["id"],
                        "original_plan_sha256": checkpoint["original_plan_sha256"],
                        "continuation_plan_sha256": receipt["plan_sha256"],
                    },
                )
                continue
            runtime.run_case(case, continuation_checkpoint=checkpoint)
    finally:
        runtime.close()


def _completion_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("artifact_root")
    parser.add_argument(
        "--build-plan",
        action="store_true",
        help="freeze a prospective exact inventory without target release",
    )
    parser.add_argument(
        "--build-continuation",
        action="store_true",
        help="freeze one no-send successor plan for a stopped campaign",
    )
    parser.add_argument(
        "--continue-existing",
        action="store_true",
        help="reopen the stopped campaign without starting or reseeding it",
    )
    parser.add_argument(
        "--prior-plan", type=Path, help="immutable original plan for continuation evidence"
    )
    parser.add_argument(
        "--receipt-path", type=Path, help="new host preflight receipt for the continuation plan"
    )
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--js-package", type=Path)
    parser.add_argument("--service-image")
    parser.add_argument("--node-image")
    parser.add_argument("--operator-port", type=int)
    parser.add_argument("--campaign-id")
    parser.add_argument("--budget-account-id")
    parser.add_argument("--financial-owner-id")
    parser.add_argument(
        "--release",
        action="store_true",
        help="start the already-authorized finite target after preflight",
    )
    args = parser.parse_args(argv)
    return args


if __name__ == "__main__":
    main()
