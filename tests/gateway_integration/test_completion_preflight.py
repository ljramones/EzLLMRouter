"""No-send controls for the fixed DEV-12 Completion 02 scenario gate."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import json
import os
import sqlite3
import sys
import unittest

from tools.gateway.evidence.dev12_completion_catalog import CaseHandler, REQUIRED_PAIRS, SCENARIOS
from tools.gateway.evidence.dev12_completion_preflight import (
    _fixture_path_for_scenario,
    main,
    mounted_source_identity,
    validate,
    verify_case_result,
)


def ingress_identity(context, case):
    return context.execute_case(case)


def authority_recovery(context, case):
    return context.execute_case(case)


def client_contract(context, case):
    return context.execute_case(case)


def native_accounting(context, case):
    return context.execute_case(case)


def retrieval_workflow(context, case):
    return context.execute_case(case)


def operator_identity(context, case):
    return context.execute_case(case)


def operator_reporting(context, case):
    return context.execute_case(case)


def persistence_migration(context, case):
    return context.execute_case(case)


def recovery_chain(context, case):
    return context.execute_case(case)


def nominal_file_exists(context, case):
    return Path(__file__).is_file()


_RUNS = {
    fn.__name__: fn
    for fn in (
        ingress_identity,
        authority_recovery,
        client_contract,
        native_accounting,
        retrieval_workflow,
        operator_identity,
        operator_reporting,
        persistence_migration,
        recovery_chain,
    )
}


class CompletionPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(
            prefix=".dev12-preflight-test-",
            dir=Path(
                os.environ.get("DEV12_TEST_SCRATCH_ROOT", Path(__file__).resolve().parents[2])
            ),
        )
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        wheel = self.root / "client.whl"
        wheel.write_bytes(b"test wheel bytes")
        tarball = self.root / "client.tgz"
        tarball.write_bytes(b"test tarball bytes")
        self.images = {"sha256:" + "a" * 64, "sha256:" + "b" * 64}
        ref = lambda file: {"path": str(file), "sha256": sha256(file.read_bytes()).hexdigest()}
        source_sha = sha256(Path(__file__).read_bytes()).hexdigest()
        self.handlers = {
            name: CaseHandler(
                name,
                str(Path(__file__).resolve()),
                source_sha,
                frozenset(
                    pair
                    for pair in REQUIRED_PAIRS
                    if SCENARIOS[pair[0]].variants[pair[1]].handler == name
                ),
                run,
            )
            for name, run in _RUNS.items()
        }
        chain_ids = {
            variant: f"case.recovery_chain.{variant}"
            for variant in SCENARIOS["recovery_chain"].variants
        }
        order = (
            "unknown_pause",
            "retained_receipt",
            "authorized_late_append",
            "denied_resume",
            "eligible_resume",
        )
        cases = []
        for scenario, variant in sorted(REQUIRED_PAIRS):
            scenario_spec = SCENARIOS[scenario]
            spec = scenario_spec.variants[variant]
            ident = f"case.{scenario}.{variant}"
            recovery = scenario == "recovery_chain"
            sends = max(
                spec.minimum_possible_sends,
                int(
                    "receiver" in spec.required_stages
                    and spec.phase not in {"late_evidence", "resume"}
                ),
            )
            if (scenario, variant) == ("t50_e", "composed"):
                sends = 0  # Imported historical underbound; no new target admission.
            prerequisites = []
            late_dependencies = []
            if recovery and variant != "unknown_pause":
                prerequisites = [chain_ids[order[order.index(variant) - 1]]]
                if variant in {"denied_resume", "eligible_resume"}:
                    late_dependencies = [chain_ids["authorized_late_append"]]
            cases.append(
                {
                    "id": ident,
                    "scenario_id": scenario,
                    "variant": variant,
                    "assurance_ids": list(scenario_spec.assurance_ids),
                    "handler": spec.handler,
                    "handler_source_sha256": source_sha,
                    "prerequisites": prerequisites,
                    "late_dependencies": late_dependencies,
                    "attempt_group": "attempt.recovery" if recovery else ident,
                    "scope": "campaign.new",
                    "installed_client_mode": "both",
                    "fixture": ref(_fixture_path_for_scenario(scenario)),
                    "source_tree": "c" * 40,
                    "build": ref(Path(__file__)),
                    "max_admissions": sends,
                    "max_possible_sends": sends,
                    "max_exposure_decimal": "0.010000000" if sends else "0.000000000",
                    "expected_stages": list(spec.required_stages),
                    "expected_rejection": None,
                    "terminal_status": "completed",
                    "evidence_paths": [str(self.root / "cases" / (ident + ".json"))],
                    "predicates": list(spec.assertion_ids),
                    "evidence_kind": "new",
                    "reuse_identity": None,
                    "phase": spec.phase,
                }
            )
        fresh_ids = {
            case["id"]
            for case in cases
            if case["max_possible_sends"] or case["scenario_id"] == "recovery_chain"
        }
        reporting_order = {
            "t61": ("t60", "recovery_chain.authorized_late_append"),
            "t62_a": ("t60",),
            "t62_b": ("recovery_chain.authorized_late_append",),
            "t62_c": ("t60",),
            "t62_d": ("t60",),
            "t62_e": ("t60",),
            "t64": ("t61", "t62_a", "t62_b", "t62_c", "t62_d", "t62_e"),
            "t65": ("t64",),
        }
        case_ids = {f"{case['scenario_id']}.{case['variant']}": case["id"] for case in cases}
        for case in cases:
            if case["scenario_id"] in reporting_order:
                case["prerequisites"].extend(
                    case_ids[name if "." in name else name + ".composed"]
                    for name in reporting_order[case["scenario_id"]]
                )
            if case["phase"] == "terminal":
                case["prerequisites"] = sorted(fresh_ids - {case["id"]})
        ordered, pending = [], list(cases)
        while pending:
            ready = next(
                (
                    case
                    for case in pending
                    if set(case["prerequisites"] + case["late_dependencies"]).issubset(
                        {row["id"] for row in ordered}
                    )
                ),
                None,
            )
            if ready is None:
                raise AssertionError("test catalog contains a dependency cycle")
            pending.remove(ready)
            ordered.append(ready)
        cases = ordered
        self.plan = {
            "source_tree": "c" * 40,
            "envelope": {
                "campaign_id": "campaign.new",
                "budget_account_id": "budget.new",
                "financial_owner_id": "team.new",
                "max_admissions": 512,
                "max_possible_sends": 512,
                "max_inflight": 2,
                "ceiling_decimal": "6.000000000",
                "window_hours": 24,
                "real_provider_calls": 0,
                "rerun_headroom_admissions": 2,
                "rerun_headroom_sends": 2,
                "rerun_headroom_decimal": "0.020000000",
                "preexisting_exposure_decimal": "0.000000000",
            },
            "artifacts": [
                {"kind": "python_wheel", **ref(wheel)},
                {"kind": "js_tarball", **ref(tarball)},
                {"kind": "service_image", "path": "sha256:" + "a" * 64, "sha256": "a" * 64},
                {"kind": "node_image", "path": "sha256:" + "b" * 64, "sha256": "b" * 64},
            ],
            "cases": cases,
        }

    def check(self, plan=None, handlers=None):
        return validate(
            plan if plan is not None else self.plan,
            handlers=handlers if handlers is not None else self.handlers,
            artifact_root=self.root,
            image_ids=self.images,
            handler_source_path=Path(__file__),
        )

    def case(self, plan, scenario, variant="composed"):
        return next(
            case
            for case in plan["cases"]
            if (case["scenario_id"], case["variant"]) == (scenario, variant)
        )

    def test_continuation_receipt_cli_requires_distinct_path_in_target_root(self):
        plan = deepcopy(self.plan)
        plan["envelope"]["preexisting_exposure_decimal"] = "0.002900002"
        plan_path = self.root / "continuation-plan.json"
        plan_path.write_text(json.dumps(plan))
        original = self.root / "preflight-receipt.json"
        distinct = self.root / "preflight-receipt-continuation1.json"
        for receipt, reaches_git in (
            (None, False),
            (original, False),
            (distinct, True),
            (self.root.parent / "outside.json", False),
        ):
            argv = ["preflight", str(plan_path), "dev12_completion_handlers", str(self.root)]
            if receipt is not None:
                argv.append(str(receipt))
            with (
                self.subTest(receipt=receipt),
                patch.object(sys, "argv", argv),
                patch(
                    "tools.gateway.evidence.dev12_completion_preflight.subprocess.run",
                    side_effect=RuntimeError("reached git source gate"),
                ),
            ):
                if reaches_git:
                    with self.assertRaisesRegex(RuntimeError, "reached git source gate"):
                        main()
                else:
                    with self.assertRaises(SystemExit):
                        main()
        plan["cases"][0]["id"] += ".continuation3"
        plan_path.write_text(json.dumps(plan))
        with (
            patch.object(
                sys,
                "argv",
                [
                    "preflight",
                    str(plan_path),
                    "dev12_completion_handlers",
                    str(self.root),
                    str(self.root / "preflight-receipt-continuation3.json"),
                ],
            ),
            patch(
                "tools.gateway.evidence.dev12_completion_preflight.subprocess.run",
                side_effect=RuntimeError("reached git source gate"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "reached git source gate"):
                main()

    def test_complete_catalog_is_repeatable_without_sending(self):
        first = self.check()
        self.assertEqual(first["status"], "PASS", first["errors"])
        self.assertEqual(first["case_count"], len(REQUIRED_PAIRS))
        self.assertEqual(self.check()["status"], "PASS")

    def test_all_labels_one_nominal_case_or_copies_fail(self):
        one = deepcopy(self.plan)
        one["cases"] = [one["cases"][0]]
        one["cases"][0]["assurance_ids"] = sorted(
            label for spec in SCENARIOS.values() for label in spec.assurance_ids
        )
        self.assertTrue(
            any("fixed scenario/variant" in error for error in self.check(one)["errors"])
        )
        copies = deepcopy(self.plan)
        copies["cases"] = [{**deepcopy(copies["cases"][0]), "id": f"copy.{n}"} for n in range(66)]
        self.assertTrue(
            any("duplicate scenario/variant" in error for error in self.check(copies)["errors"])
        )

    def test_missing_handler_changed_source_and_nominal_result_fail(self):
        handlers = dict(self.handlers)
        handlers.pop("ingress_identity")
        self.assertEqual(self.check(handlers=handlers)["status"], "BLOCKED_NO_SEND")
        changed = deepcopy(self.plan)
        self.case(changed, "t01")["handler_source_sha256"] = "0" * 64
        self.assertTrue(
            any("source identity mismatch" in error for error in self.check(changed)["errors"])
        )
        self.assertEqual(
            verify_case_result(self.plan["cases"][0], nominal_file_exists(None, None), self.root)[
                "status"
            ],
            "FAIL",
        )

    def test_recovery_chain_missing_or_nominal_dependencies_fail(self):
        missing = deepcopy(self.plan)
        missing["cases"] = [
            case
            for case in missing["cases"]
            if not (case["scenario_id"] == "recovery_chain" and case["variant"] == "unknown_pause")
        ]
        self.assertTrue(
            any("recoverable unknown" in error for error in self.check(missing)["errors"])
        )
        nominal = deepcopy(self.plan)
        self.case(nominal, "recovery_chain", "retained_receipt")["prerequisites"] = []
        self.case(nominal, "recovery_chain", "eligible_resume")["late_dependencies"] = []
        errors = self.check(nominal)["errors"]
        self.assertTrue(any("recovery chain lacks" in error for error in errors))
        self.assertTrue(any("audited resume lacks actual late append" in error for error in errors))

    def test_cycle_identity_capture_and_mixed_budget_fail(self):
        plan = deepcopy(self.plan)
        self.case(plan, "t01")["prerequisites"] = [self.case(plan, "t01")["id"]]
        self.case(plan, "t01")["evidence_paths"] = [str(self.root.parent / "outside.json")]
        plan["artifacts"][0]["sha256"] = "0" * 64
        plan["envelope"]["budget_account_id"] = "budget.synthetic.dev12.correction01"
        plan["envelope"]["rerun_headroom_decimal"] = "5.990000001"
        result = self.check(plan)
        for phrase in (
            "cyclic prerequisite",
            "evidence capture path unavailable",
            "package bytes differ",
            "distinct durable",
            "mixed inventory exceeds",
        ):
            self.assertTrue(any(phrase in error for error in result["errors"]), phrase)

    def test_three_identity_case_cannot_hide_send_bound(self):
        plan = deepcopy(self.plan)
        self.case(plan, "t60")["max_admissions"] = 1
        self.case(plan, "t60")["max_possible_sends"] = 1
        self.assertTrue(
            any("fixed scenario minimum" in error for error in self.check(plan)["errors"])
        )
        unallocated = deepcopy(self.plan)
        self.case(unallocated, "t60")["max_exposure_decimal"] = "0.000000000"
        self.assertTrue(
            any(
                "lacks a finite exposure allocation" in error
                for error in self.check(unallocated)["errors"]
            )
        )

    def test_only_terminal_imported_underbound_may_have_zero_receiver_send(self):
        historical = self.case(self.plan, "t50_e")
        self.assertEqual((historical["max_admissions"], historical["max_possible_sends"]), (0, 0))
        self.assertEqual(self.check()["status"], "PASS")
        ordinary = deepcopy(self.plan)
        self.case(ordinary, "t49_e")["max_admissions"] = 0
        self.case(ordinary, "t49_e")["max_possible_sends"] = 0
        errors = self.check(ordinary)["errors"]
        self.assertTrue(
            any("receiver case lacks a possible-send bound" in error for error in errors)
        )

    def test_continuation_binds_checkpoint_evidence_and_prior_allowance(self):
        original = deepcopy(self.plan)
        (self.root / "plan.json").write_text(json.dumps(original) + "\n")
        current = deepcopy(original)
        passed, failed = current["cases"][:2]
        passed_path = Path(passed["evidence_paths"][0])
        passed_path.parent.mkdir(exist_ok=True)
        passed_path.write_text('{"retained":"original"}\n')
        old_id = failed["id"]
        failed["id"] = old_id + ".continuation1"
        failed["evidence_paths"] = ["cases/" + failed["id"] + ".json"]
        failed["max_admissions"] = failed["max_possible_sends"] = 0
        failed["max_exposure_decimal"] = "0.000000000"
        for case in current["cases"]:
            case["prerequisites"] = [
                failed["id"] if ident == old_id else ident for ident in case["prerequisites"]
            ]
            case["late_dependencies"] = [
                failed["id"] if ident == old_id else ident for ident in case["late_dependencies"]
            ]
        current["envelope"]["preexisting_exposure_decimal"] = "0.001000000"
        campaign = {
            "campaign_id": current["envelope"]["campaign_id"],
            "budget_account_id": current["envelope"]["budget_account_id"],
            "financial_owner_id": current["envelope"]["financial_owner_id"],
            "start_at": "2026-10-26T12:00:00Z",
            "expires_at": "2026-10-27T12:00:00Z",
            "attempt_count": 2,
            "possible_send_count": 2,
            "cumulative_reserved_decimal": "0.001000000",
        }
        with sqlite3.connect(self.root / "campaign.sqlite") as database:
            database.execute("CREATE TABLE dev12_campaigns (campaign_id TEXT, record TEXT)")
            database.execute(
                "INSERT INTO dev12_campaigns VALUES (?,?)",
                (campaign["campaign_id"], json.dumps(campaign)),
            )
        checkpoint = {
            "passed_ids": [passed["id"]],
            "failed_id": old_id,
            "last_campaign": campaign,
            "original_start_at": campaign["start_at"],
            "original_expires_at": campaign["expires_at"],
        }
        with patch(
            "tools.gateway.evidence.dev12_completion_runner.continuation_checkpoint",
            return_value=checkpoint,
        ):
            good = self.check(current)
            self.assertEqual(good["status"], "PASS", good["errors"])
            self.assertGreaterEqual(good["max_admissions"], campaign["attempt_count"])
            mismatched = deepcopy(current)
            mismatched["envelope"]["preexisting_exposure_decimal"] = "0.002000000"
            self.assertTrue(
                any(
                    "continuation prior exposure" in error
                    for error in self.check(mismatched)["errors"]
                )
            )
            passed_path.unlink()
            self.assertTrue(
                any(
                    "checkpoint-verified passed evidence missing" in error
                    for error in self.check(current)["errors"]
                )
            )
        nominal = deepcopy(self.plan)
        self.case(nominal, "t50_e")["phase"] = "normal"
        errors = self.check(nominal)["errors"]
        self.assertTrue(
            any("receiver case lacks a possible-send bound" in error for error in errors)
        )

    def test_second_continuation_binds_first_plan_receipt_failure_and_counters(self):
        original = deepcopy(self.plan)
        (self.root / "plan.json").write_text(json.dumps(original) + "\n")
        first = deepcopy(original)
        passed = first["cases"][0]
        failed = self.case(first, "t24_b", "partial_write")
        passed_path = self.root / passed["evidence_paths"][0]
        passed_path.parent.mkdir(exist_ok=True)
        passed_path.write_text('{"retained":"original"}\n')
        base = failed["id"]
        first_id = base + ".continuation1"
        failed["id"] = first_id
        failed["evidence_paths"] = ["cases/" + first_id + ".json"]
        failed["max_admissions"] = failed["max_possible_sends"] = 0
        failed["max_exposure_decimal"] = "0.000000000"
        for case in first["cases"]:
            case["prerequisites"] = [
                first_id if value == base else value for value in case["prerequisites"]
            ]
            case["late_dependencies"] = [
                first_id if value == base else value for value in case["late_dependencies"]
            ]
        first["envelope"]["preexisting_exposure_decimal"] = "0.002900002"
        first_bytes = (json.dumps(first) + "\n").encode()
        (self.root / "plan.continuation1.json").write_bytes(first_bytes)
        receipt = {
            "plan_sha256": sha256(first_bytes).hexdigest(),
            "source_tree": first["source_tree"],
            "case_count": len(first["cases"]),
        }
        receipt_path = self.root / "preflight-receipt-continuation1.json"
        receipt_path.write_text(json.dumps(receipt) + "\n")
        failed_path = self.root / failed["evidence_paths"][0]
        failed_path.write_text('{"retained":"first failure"}\n')
        second = deepcopy(first)
        second_id = base + ".continuation2"
        for case in second["cases"]:
            case["prerequisites"] = [
                second_id if value == first_id else value for value in case["prerequisites"]
            ]
            case["late_dependencies"] = [
                second_id if value == first_id else value for value in case["late_dependencies"]
            ]
            if case["id"] == first_id:
                case["id"] = second_id
                case["evidence_paths"] = ["cases/" + second_id + ".json"]
        campaign = {
            "campaign_id": second["envelope"]["campaign_id"],
            "budget_account_id": second["envelope"]["budget_account_id"],
            "financial_owner_id": second["envelope"]["financial_owner_id"],
            "start_at": "2026-10-26T21:54:14Z",
            "expires_at": "2026-10-27T21:54:14Z",
            "attempt_count": 11,
            "possible_send_count": 11,
            "paused": False,
            "cumulative_reserved_decimal": "0.002900002",
        }
        with sqlite3.connect(self.root / "campaign.sqlite") as database:
            database.execute("CREATE TABLE dev12_campaigns (campaign_id TEXT, record TEXT)")
            database.execute(
                "INSERT INTO dev12_campaigns VALUES (?,?)",
                (campaign["campaign_id"], json.dumps(campaign)),
            )
        checkpoint = {
            "passed_ids": [passed["id"]],
            "failed_id": base,
            "latest_failed_id": first_id,
            "last_campaign": campaign,
            "original_start_at": campaign["start_at"],
            "original_expires_at": campaign["expires_at"],
        }
        with patch(
            "tools.gateway.evidence.dev12_completion_runner.continuation_checkpoint",
            return_value=checkpoint,
        ):
            self.assertEqual(self.check(second)["status"], "PASS", self.check(second)["errors"])
            receipt["plan_sha256"] = "0" * 64
            receipt_path.write_text(json.dumps(receipt) + "\n")
            self.assertTrue(
                any("prior continuation receipt" in error for error in self.check(second)["errors"])
            )
            receipt["plan_sha256"] = sha256(first_bytes).hexdigest()
            receipt_path.write_text(json.dumps(receipt) + "\n")
            failed_path.unlink()
            self.assertTrue(
                any(
                    "prior continuation failed evidence absent" in error
                    for error in self.check(second)["errors"]
                )
            )

        second_t47 = self.case(second, "t47_a")
        second_t47["evidence_paths"] = ["cases/" + second_t47["id"] + ".json"]
        second_t47["max_admissions"] = second_t47["max_possible_sends"] = 2
        second_bytes = (json.dumps(second) + "\n").encode()
        (self.root / "plan.continuation2.json").write_bytes(second_bytes)
        second_receipt = {
            "plan_sha256": sha256(second_bytes).hexdigest(),
            "source_tree": second["source_tree"],
            "case_count": len(second["cases"]),
        }
        (self.root / "preflight-receipt-continuation2.json").write_text(
            json.dumps(second_receipt) + "\n"
        )
        third = deepcopy(second)
        third["envelope"]["preexisting_exposure_decimal"] = "0.008000003"
        third_failed = self.case(third, "t47_a")
        third_old_id = third_failed["id"]
        third_id = third_old_id + ".continuation3"
        (self.root / third_failed["evidence_paths"][0]).write_text('{"retained":"third stop"}\n')
        third_failed["id"] = third_id
        third_failed["evidence_paths"] = ["cases/" + third_id + ".json"]
        third_failed["max_admissions"] = third_failed["max_possible_sends"] = 0
        third_failed["max_exposure_decimal"] = "0.000000000"
        for case in third["cases"]:
            case["prerequisites"] = [
                third_id if value == third_old_id else value for value in case["prerequisites"]
            ]
            case["late_dependencies"] = [
                third_id if value == third_old_id else value for value in case["late_dependencies"]
            ]
        passed_ids = [case["id"] for case in second["cases"][:25]]
        for case in second["cases"][:25]:
            evidence_path = self.root / case["evidence_paths"][0]
            evidence_path.parent.mkdir(exist_ok=True)
            evidence_path.write_text('{"retained":"verified"}\n')
        campaign.update(
            attempt_count=35, possible_send_count=35, cumulative_reserved_decimal="0.008000003"
        )
        with sqlite3.connect(self.root / "campaign.sqlite") as database:
            database.execute("UPDATE dev12_campaigns SET record=?", (json.dumps(campaign),))
        checkpoint.update(
            passed_ids=passed_ids,
            failed_id=third_old_id,
            latest_failed_id=third_old_id,
            continuation_number=3,
            failed_attempt_ids=["python-attempt", "commonjs-attempt"],
            last_campaign=campaign,
        )
        with patch(
            "tools.gateway.evidence.dev12_completion_runner.continuation_checkpoint",
            return_value=checkpoint,
        ):
            good = self.check(third)
            self.assertEqual(good["status"], "PASS", good["errors"])
            self.assertGreaterEqual(good["max_admissions"], 35)
            tampered = deepcopy(third)
            self.case(tampered, "t24_b", "partial_write")["id"] = base
            self.assertTrue(
                any(
                    "continuation changes retained case" in error
                    for error in self.check(tampered)["errors"]
                )
            )
            checkpoint["failed_attempt_ids"] = ["same-attempt", "same-attempt"]
            self.assertTrue(
                any(
                    "retained installed-client submissions are unverified" in error
                    for error in self.check(third)["errors"]
                )
            )

        third_t49 = self.case(third, "t49_d")
        third_t49["evidence_paths"] = ["cases/" + third_t49["id"] + ".json"]
        third_t49["max_admissions"] = third_t49["max_possible_sends"] = 3
        third_bytes = (json.dumps(third) + "\n").encode()
        (self.root / "plan.continuation3.json").write_bytes(third_bytes)
        (self.root / "preflight-receipt-continuation3.json").write_text(
            json.dumps(
                {
                    "plan_sha256": sha256(third_bytes).hexdigest(),
                    "source_tree": third["source_tree"],
                    "case_count": len(third["cases"]),
                }
            )
            + "\n"
        )
        fourth = deepcopy(third)
        fourth["envelope"]["preexisting_exposure_decimal"] = "0.012200008"
        fourth_failed = self.case(fourth, "t49_d")
        fourth_old_id = fourth_failed["id"]
        fourth_id = fourth_old_id + ".continuation4"
        (self.root / fourth_failed["evidence_paths"][0]).write_text('{"retained":"fourth stop"}\n')
        fourth_failed["id"] = fourth_id
        fourth_failed["evidence_paths"] = ["cases/" + fourth_id + ".json"]
        fourth_failed["max_admissions"] = fourth_failed["max_possible_sends"] = 0
        fourth_failed["max_exposure_decimal"] = "0.000000000"
        for case in fourth["cases"]:
            case["prerequisites"] = [
                fourth_id if value == fourth_old_id else value for value in case["prerequisites"]
            ]
            case["late_dependencies"] = [
                fourth_id if value == fourth_old_id else value
                for value in case["late_dependencies"]
            ]
        fourth_passed = [case["id"] for case in third["cases"][:40]]
        for case in third["cases"][:40]:
            evidence_path = self.root / case["evidence_paths"][0]
            evidence_path.parent.mkdir(exist_ok=True)
            evidence_path.write_text('{"retained":"verified"}\n')
        t47_source = self.root / "cases/case.t47_a.composed.json"
        t47_ref = {
            "path": str(t47_source),
            "sha256": sha256(t47_source.read_bytes()).hexdigest(),
            "bytes": t47_source.stat().st_size,
        }
        campaign.update(
            attempt_count=51, possible_send_count=51, cumulative_reserved_decimal="0.012200008"
        )
        with sqlite3.connect(self.root / "campaign.sqlite") as database:
            database.execute("UPDATE dev12_campaigns SET record=?", (json.dumps(campaign),))
        checkpoint.update(
            passed_ids=fourth_passed,
            failed_id=fourth_old_id,
            latest_failed_id=fourth_old_id,
            continuation_number=4,
            failed_attempt_ids=["late-1", "late-2", "late-3"],
            retained_t47_live_attempt_ids=["python-attempt", "commonjs-attempt"],
            retained_t47_live_evidence=t47_ref,
            last_campaign=campaign,
        )
        with patch(
            "tools.gateway.evidence.dev12_completion_runner.continuation_checkpoint",
            return_value=checkpoint,
        ):
            good = self.check(fourth)
            self.assertEqual(good["status"], "PASS", good["errors"])
            self.assertGreaterEqual(good["max_admissions"], 51)
            checkpoint["retained_t47_live_attempt_ids"] = ["same", "same"]
            self.assertTrue(
                any(
                    "retained installed-client submissions are unverified" in error
                    for error in self.check(fourth)["errors"]
                )
            )

        fourth_t60 = self.case(fourth, "t60")
        fourth_t60["evidence_paths"] = ["cases/" + fourth_t60["id"] + ".json"]
        fourth_t60["max_admissions"] = fourth_t60["max_possible_sends"] = 3
        fourth_bytes = (json.dumps(fourth) + "\n").encode()
        (self.root / "plan.continuation4.json").write_bytes(fourth_bytes)
        (self.root / "preflight-receipt-continuation4.json").write_text(
            json.dumps(
                {
                    "plan_sha256": sha256(fourth_bytes).hexdigest(),
                    "source_tree": fourth["source_tree"],
                    "case_count": len(fourth["cases"]),
                }
            )
            + "\n"
        )
        fifth = deepcopy(fourth)
        fifth["envelope"]["preexisting_exposure_decimal"] = "0.020400018"
        fifth_failed = self.case(fifth, "t60")
        fifth_old_id = fifth_failed["id"]
        fifth_id = fifth_old_id + ".continuation5"
        fifth_failed["id"] = fifth_id
        fifth_failed["evidence_paths"] = ["cases/" + fifth_id + ".json"]
        fifth_failed["max_admissions"] = fifth_failed["max_possible_sends"] = 0
        fifth_failed["max_exposure_decimal"] = "0.000000000"
        for case in fifth["cases"]:
            case["prerequisites"] = [
                fifth_id if value == fifth_old_id else value for value in case["prerequisites"]
            ]
            case["late_dependencies"] = [
                fifth_id if value == fifth_old_id else value for value in case["late_dependencies"]
            ]
        fifth_passed = [case["id"] for case in fourth["cases"][:52]]
        for case in fourth["cases"][:52]:
            evidence_path = self.root / case["evidence_paths"][0]
            evidence_path.parent.mkdir(exist_ok=True)
            evidence_path.write_text('{"retained":"verified"}\n')
        campaign.update(
            attempt_count=76, possible_send_count=76, cumulative_reserved_decimal="0.020400018"
        )
        with sqlite3.connect(self.root / "campaign.sqlite") as database:
            database.execute("UPDATE dev12_campaigns SET record=?", (json.dumps(campaign),))
        t47_ref["sha256"] = sha256(t47_source.read_bytes()).hexdigest()
        t47_ref["bytes"] = t47_source.stat().st_size
        checkpoint.update(
            passed_ids=fifth_passed,
            failed_id=fifth_old_id,
            latest_failed_id=fifth_old_id,
            continuation_number=5,
            retained_t60_positive_attempt_ids=["owner", "vega", "orion"],
            retained_t47_live_attempt_ids=["python-attempt", "commonjs-attempt"],
            retained_t47_live_evidence=t47_ref,
            last_campaign=campaign,
        )
        with patch(
            "tools.gateway.evidence.dev12_completion_runner.continuation_checkpoint",
            return_value=checkpoint,
        ):
            good = self.check(fifth)
            self.assertEqual(good["status"], "PASS", good["errors"])
            self.assertGreaterEqual(good["max_admissions"], 76)
            checkpoint["retained_t60_positive_attempt_ids"] = ["owner", "owner", "orion"]
            self.assertTrue(
                any(
                    "retained T60 positive attempts are unverified" in error
                    for error in self.check(fifth)["errors"]
                )
            )

    def test_populated_reporting_requires_actual_prior_cases(self):
        plan = deepcopy(self.plan)
        self.case(plan, "t62_b")["prerequisites"] = []
        self.case(plan, "t64")["prerequisites"] = []
        errors = self.check(plan)["errors"]
        self.assertTrue(
            any(
                "missing populated reporting prerequisite recovery_chain/authorized_late_append"
                in error
                for error in errors
            )
        )
        self.assertTrue(
            any(
                "missing populated reporting prerequisite t61/composed" in error for error in errors
            )
        )

    def test_executable_list_must_follow_declared_dependency_order(self):
        plan = deepcopy(self.plan)
        case = self.case(plan, "t62_b")
        plan["cases"].remove(case)
        plan["cases"].insert(0, case)
        self.assertTrue(
            any(
                "executable order precedes prerequisite" in error
                for error in self.check(plan)["errors"]
            )
        )

    def test_case_id_cannot_escape_retained_case_directory(self):
        plan = deepcopy(self.plan)
        self.case(plan, "t01")["id"] = "../outside"
        self.assertTrue(
            any("duplicate/invalid case ID" in error for error in self.check(plan)["errors"])
        )

    def test_runtime_rejects_unexecuted_or_missing_observation(self):
        case = self.case(self.plan, "t01")
        nominal = {
            "status": "PASS",
            "observations": [],
            "assertions": [
                {
                    "id": ident,
                    "passed": True,
                    "executed": True,
                    "evidence_paths": ["not-retained.json"],
                    "detail": "PASS",
                }
                for ident in case["predicates"]
            ],
        }
        self.assertTrue(
            any(
                "required stage observations missing" in error
                for error in verify_case_result(case, nominal, self.root)["errors"]
            )
        )
        evidence = Path(case["evidence_paths"][0])
        evidence.parent.mkdir(exist_ok=True)
        evidence.write_text('{"actual":"rejected"}\n')
        observation = {
            "stage": "ingress",
            "evidence_path": str(evidence),
            "sha256": sha256(evidence.read_bytes()).hexdigest(),
            "case_id": case["id"],
            "attempt_group": case["attempt_group"],
            "observed": {"actual": "rejected"},
        }
        nominal["observations"] = [observation, {**observation, "stage": "admission"}]
        nominal["assertions"] = [
            {
                "id": ident,
                "passed": True,
                "executed": False,
                "evidence_paths": [str(evidence)],
                "detail": "not run",
            }
            for ident in case["predicates"]
        ]
        self.assertTrue(
            any(
                "unexecuted" in error
                for error in verify_case_result(case, nominal, self.root)["errors"]
            )
        )
        nominal["assertions"] = [
            {**row, "executed": True, "detail": "objective comparison with retained observation"}
            for row in nominal["assertions"]
        ]
        self.assertEqual(verify_case_result(case, nominal, self.root)["status"], "PASS")

        wrong_path = self.root / "other-observation.json"
        wrong_path.write_bytes(evidence.read_bytes())
        nominal["observations"] = [
            {**row, "evidence_path": str(wrong_path)} for row in nominal["observations"]
        ]
        nominal["assertions"] = [
            {**row, "evidence_paths": [str(wrong_path)]} for row in nominal["assertions"]
        ]
        self.assertTrue(
            any(
                "planned evidence paths" in error
                for error in verify_case_result(case, nominal, self.root)["errors"]
            )
        )

    def test_runtime_primary_outcome_and_rejection_are_independent(self):
        case = self.case(self.plan, "t01")
        path = Path(case["evidence_paths"][0])
        path.parent.mkdir(exist_ok=True)
        path.write_text('{"observed":"primary"}\n')
        digest = sha256(path.read_bytes()).hexdigest()
        result = {
            "status": "PASS",
            "observations": [
                {
                    "stage": stage,
                    "evidence_path": str(path),
                    "sha256": digest,
                    "case_id": case["id"],
                    "attempt_group": case["attempt_group"],
                    "observed": {"actual": "primary"},
                }
                for stage in case["expected_stages"]
            ],
            "assertions": [
                {
                    "id": ident,
                    "passed": True,
                    "executed": True,
                    "evidence_paths": [str(path)],
                    "detail": "Compared retained primary target observations",
                }
                for ident in case["predicates"]
            ],
        }
        independent = {
            "primary_attempt_id": "attempt.test.primary",
            "terminal_status": "completed",
            "rejection": None,
            "reservation_delta_decimal": "0.005000000",
            "primary_stages": [
                "ingress",
                "admission",
                "guard",
                "first_write",
                "receiver",
                "delivery",
                "settlement",
            ],
        }
        self.assertEqual(
            verify_case_result(case, result, self.root, actual=independent, require_actual=True)[
                "status"
            ],
            "PASS",
        )
        self.assertTrue(
            any(
                "runtime facts missing" in error
                for error in verify_case_result(case, result, self.root, require_actual=True)[
                    "errors"
                ]
            )
        )
        changed = dict(independent, terminal_status="unknown")
        self.assertTrue(
            any(
                "terminal state differs" in error
                for error in verify_case_result(case, result, self.root, actual=changed)["errors"]
            )
        )
        over_allocated = dict(independent, reservation_delta_decimal="0.010000001")
        self.assertTrue(
            any(
                "USD reservation allocation" in error
                for error in verify_case_result(case, result, self.root, actual=over_allocated)[
                    "errors"
                ]
            )
        )
        rejected = deepcopy(case)
        rejected["expected_rejection"] = {
            "stage": "guard",
            "code": "FDC_REJECTED",
            "http_status": 409,
        }
        rejected["terminal_status"] = "failed"
        stopped = dict(
            independent,
            terminal_status="failed",
            rejection=rejected["expected_rejection"],
            primary_stages=["ingress", "admission", "guard"],
        )
        self.assertEqual(
            verify_case_result(rejected, result, self.root, actual=stopped, require_actual=True)[
                "status"
            ],
            "PASS",
        )
        leaked = dict(
            stopped, primary_stages=["ingress", "admission", "guard", "first_write", "receiver"]
        )
        self.assertTrue(
            any(
                "forbidden later stage" in error
                for error in verify_case_result(rejected, result, self.root, actual=leaked)[
                    "errors"
                ]
            )
        )
        wrong_code = dict(stopped, rejection={**stopped["rejection"], "code": "OTHER_REJECTION"})
        self.assertTrue(
            any(
                "rejection differs" in error
                for error in verify_case_result(rejected, result, self.root, actual=wrong_code)[
                    "errors"
                ]
            )
        )
        delivery_failure = deepcopy(case)
        delivery_failure["expected_rejection"] = {
            "stage": "delivery",
            "code": "RESULT_VALIDATION_FAILED",
            "http_status": 422,
        }
        delivery_failure["terminal_status"] = "failed"
        failed_with_charge = dict(
            independent, terminal_status="failed", rejection=delivery_failure["expected_rejection"]
        )
        self.assertEqual(
            verify_case_result(
                delivery_failure, result, self.root, actual=failed_with_charge, require_actual=True
            )["status"],
            "PASS",
        )

    def test_offline_client_artifacts_do_not_replace_live_client_coverage(self):
        plan = deepcopy(self.plan)
        for case in plan["cases"]:
            if case["max_possible_sends"]:
                case["installed_client_mode"] = "none"
        result = self.check(plan)
        self.assertTrue(
            any("absent from fresh target submissions" in error for error in result["errors"])
        )

    def test_rejection_metadata_and_evidence_sources_must_be_precise(self):
        self.assertEqual(
            _fixture_path_for_scenario("t03"),
            Path(__file__).resolve().parents[2] / "tests/development_slice/request.json",
        )
        plan = deepcopy(self.plan)
        case = self.case(plan, "t01")
        case["expected_rejection"] = {"stage": "ingress", "code": "bad code", "http_status": True}
        self.assertTrue(
            any("terminal/rejection expectation" in error for error in self.check(plan)["errors"])
        )
        wrong_fixture = deepcopy(self.plan)
        self.case(wrong_fixture, "t48_a")["fixture"] = {
            "path": str(Path(__file__)),
            "sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        }
        self.assertTrue(
            any(
                "fixture is not the fixed scenario input" in error
                for error in self.check(wrong_fixture)["errors"]
            )
        )
        wrong_build = deepcopy(self.plan)
        self.case(wrong_build, "t01")["build"] = {
            "path": wrong_build["artifacts"][0]["path"],
            "sha256": wrong_build["artifacts"][0]["sha256"],
        }
        self.assertTrue(
            any(
                "build does not identify reviewed handler" in error
                for error in self.check(wrong_build)["errors"]
            )
        )

    def test_browser_assets_and_capture_source_bind_mount_identity(self):
        web = self.root / "web" / "usage_costs_view.js"
        browser = self.root / "tests" / "operator_console" / "dev12_completion_browser.cjs"
        request = self.root / "tests" / "development_slice" / "request.json"
        scenarios = self.root / "tests" / "tool_cycle" / "scenarios.json"
        web.parent.mkdir(parents=True)
        browser.parent.mkdir(parents=True)
        request.parent.mkdir(parents=True)
        scenarios.parent.mkdir(parents=True)
        web.write_text("const view = 1;\n")
        browser.write_text("const capture = 1;\n")
        request.write_text('{"request":1}\n')
        scenarios.write_text('{"scenarios":1}\n')
        first = mounted_source_identity(self.root)
        self.assertEqual(first["file_count"], 4)
        web.write_text("const view = 2;\n")
        self.assertNotEqual(mounted_source_identity(self.root)["sha256"], first["sha256"])
        web.write_text("const view = 1;\n")
        browser.write_text("const capture = 2;\n")
        self.assertNotEqual(mounted_source_identity(self.root)["sha256"], first["sha256"])
        browser.write_text("const capture = 1;\n")
        request.write_text('{"request":2}\n')
        self.assertNotEqual(mounted_source_identity(self.root)["sha256"], first["sha256"])
        request.write_text('{"request":1}\n')
        scenarios.write_text('{"scenarios":2}\n')
        self.assertNotEqual(mounted_source_identity(self.root)["sha256"], first["sha256"])
        scenarios.unlink()
        with self.assertRaises(FileNotFoundError):
            mounted_source_identity(self.root)

    def test_unversioned_database_is_refused_without_adoption_or_mutation(self):
        from ezllmrouter_server.store import SQLiteStore

        path = self.root / "unversioned.sqlite"
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE submissions (record TEXT)")
            connection.execute("INSERT INTO submissions VALUES (?)", ('{"attempt":"retained"}',))
        before = path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "unversioned database"):
            SQLiteStore(path)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(Path(str(path) + "-wal").exists())

    def test_browser_attestation_requires_exact_target_or_retained_port_forward(self):
        from tools.gateway.evidence.dev12_completion_operator_handlers import _browser_attestation

        screenshot = self.root / "screen.png"
        screenshot.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic test capture")
        script = Path(__file__).resolve()
        report = {
            "attempts": [{"attempt_id": "attempt.synthetic.1"}],
            "total": {"known_usd": "0.010000000"},
        }
        direct_url = "http://127.0.0.1:37771"
        runtime = SimpleNamespace(
            root=self.root,
            operator_url=direct_url,
            plan={"source_tree": "c" * 40, "envelope": {"campaign_id": "campaign.synthetic.test"}},
        )
        census = {
            "submissions": 1,
            "usage_revisions": 1,
            "receiver_arrivals": 1,
            "attempt_count": 1,
            "possible_send_count": 1,
        }
        ledger = {
            **census,
            "files": {
                name: {"present": False, "bytes": 0, "sha256": None}
                for name in (
                    "receiver.jsonl",
                    "guard.jsonl",
                    "send-events.jsonl",
                    "receiver-receipts.jsonl",
                )
            },
        }
        payload = {
            "kind": "dev12_controlled_browser_observation_v1",
            "campaign_id": runtime.plan["envelope"]["campaign_id"],
            "source_tree": runtime.plan["source_tree"],
            "operator_url": direct_url,
            "browser_url": direct_url,
            "port_forward": None,
            "target_probe": {
                "build_fingerprint": "a" * 64,
                "report_attempt_ids_sha256": sha256(b"attempt.synthetic.1").hexdigest(),
                "report_total": report["total"],
            },
            "capture_source": str(script.relative_to(Path(__file__).resolve().parents[2])),
            "capture_source_sha256": sha256(script.read_bytes()).hexdigest(),
            "screenshots": [
                {"path": "screen.png", "sha256": sha256(screenshot.read_bytes()).hexdigest()}
            ],
            "browser": {},
            "ledger_before": ledger,
            "ledger_after": ledger,
            "local_get_count": 2,
        }
        attestation = self.root / "operator-browser-evidence.json"
        with (
            patch(
                "tools.gateway.evidence.dev12_completion_preflight.mounted_source_identity",
                return_value={"sha256": "a" * 64},
            ),
            patch(
                "tools.gateway.evidence.dev12_completion_operator_handlers._census",
                return_value=census,
            ),
        ):
            attestation.write_text(json.dumps(payload))
            self.assertEqual(_browser_attestation(runtime, attestation.name, report)[0], payload)
            payload["browser_url"] = "http://127.0.0.1:37772"
            attestation.write_text(json.dumps(payload))
            with self.assertRaisesRegex(AssertionError, "port-forward"):
                _browser_attestation(runtime, attestation.name, report)
            mapping = self.root / "local-forward.json"
            mapping.write_text('{"from":"37771","to":"37772"}\n')
            payload["port_forward"] = {
                "from": direct_url,
                "to": payload["browser_url"],
                "method": "local_port_forward",
                "evidence_path": mapping.name,
                "sha256": sha256(mapping.read_bytes()).hexdigest(),
            }
            attestation.write_text(json.dumps(payload))
            self.assertEqual(_browser_attestation(runtime, attestation.name, report)[0], payload)
            mapping.write_text('{"from":"wrong"}\n')
            with self.assertRaisesRegex(AssertionError, "mapping evidence"):
                _browser_attestation(runtime, attestation.name, report)


if __name__ == "__main__":
    unittest.main()
