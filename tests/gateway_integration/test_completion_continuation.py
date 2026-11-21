"""CompletionContinuationTests behaviour regressions."""

from __future__ import annotations

import unittest
from tests.gateway_integration.completion_preflight_support import CompletionPreflightFixture


class CompletionContinuationTests(CompletionPreflightFixture, unittest.TestCase):
    def test_continuation_receipt_cli_requires_distinct_path_in_target_root(self):
        from tests.gateway_integration import test_completion_preflight as _api

        plan = _api.deepcopy(self.plan)
        plan["envelope"]["preexisting_exposure_decimal"] = "0.002900002"
        plan_path = self.root / "continuation-plan.json"
        plan_path.write_text(_api.json.dumps(plan))
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
                _api.patch.object(_api.sys, "argv", argv),
                _api.patch(
                    "tools.gateway.evidence.dev12_completion_preflight.subprocess.run",
                    side_effect=RuntimeError("reached git source gate"),
                ),
            ):
                if reaches_git:
                    with self.assertRaisesRegex(RuntimeError, "reached git source gate"):
                        _api.main()
                else:
                    with self.assertRaises(SystemExit):
                        _api.main()
        plan["cases"][0]["id"] += ".continuation3"
        plan_path.write_text(_api.json.dumps(plan))
        with (
            _api.patch.object(
                _api.sys,
                "argv",
                [
                    "preflight",
                    str(plan_path),
                    "dev12_completion_handlers",
                    str(self.root),
                    str(self.root / "preflight-receipt-continuation3.json"),
                ],
            ),
            _api.patch(
                "tools.gateway.evidence.dev12_completion_preflight.subprocess.run",
                side_effect=RuntimeError("reached git source gate"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "reached git source gate"):
                _api.main()

    def test_continuation_binds_checkpoint_evidence_and_prior_allowance(self):
        from tests.gateway_integration import test_completion_preflight as _api

        original = _api.deepcopy(self.plan)
        (self.root / "plan.json").write_text(_api.json.dumps(original) + "\n")
        current = _api.deepcopy(original)
        passed, failed = current["cases"][:2]
        passed_path = _api.Path(passed["evidence_paths"][0])
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
        with _api.sqlite3.connect(self.root / "campaign.sqlite") as database:
            database.execute("CREATE TABLE dev12_campaigns (campaign_id TEXT, record TEXT)")
            database.execute(
                "INSERT INTO dev12_campaigns VALUES (?,?)",
                (campaign["campaign_id"], _api.json.dumps(campaign)),
            )
        checkpoint = {
            "passed_ids": [passed["id"]],
            "failed_id": old_id,
            "last_campaign": campaign,
            "original_start_at": campaign["start_at"],
            "original_expires_at": campaign["expires_at"],
        }
        with _api.patch(
            "tools.gateway.evidence.dev12_completion_runner.continuation_checkpoint",
            return_value=checkpoint,
        ):
            good = self.check(current)
            self.assertEqual(good["status"], "PASS", good["errors"])
            self.assertGreaterEqual(good["max_admissions"], campaign["attempt_count"])
            mismatched = _api.deepcopy(current)
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
        nominal = _api.deepcopy(self.plan)
        self.case(nominal, "t50_e")["phase"] = "normal"
        errors = self.check(nominal)["errors"]
        self.assertTrue(
            any("receiver case lacks a possible-send bound" in error for error in errors)
        )

    def test_second_continuation_binds_first_plan_receipt_failure_and_counters(self):
        from tests.gateway_integration import test_completion_preflight as _api

        base, campaign, checkpoint, second = _check_second_continuation_receipt_and_failure(
            _api, self
        )

        third = _check_third_continuation_counters(_api, base, campaign, checkpoint, second, self)

        fourth, t47_ref, t47_source = _check_fourth_continuation_retained_attempts(
            _api, campaign, checkpoint, self, third
        )

        _check_fifth_continuation_retained_attempts(
            _api, campaign, checkpoint, fourth, self, t47_ref, t47_source
        )


def _check_second_continuation_receipt_and_failure(_api, self):
    original = _api.deepcopy(self.plan)
    (self.root / "plan.json").write_text(_api.json.dumps(original) + "\n")
    first = _api.deepcopy(original)
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
    first_bytes = (_api.json.dumps(first) + "\n").encode()
    (self.root / "plan.continuation1.json").write_bytes(first_bytes)
    receipt = {
        "plan_sha256": _api.sha256(first_bytes).hexdigest(),
        "source_tree": first["source_tree"],
        "case_count": len(first["cases"]),
    }
    receipt_path = self.root / "preflight-receipt-continuation1.json"
    receipt_path.write_text(_api.json.dumps(receipt) + "\n")
    failed_path = self.root / failed["evidence_paths"][0]
    failed_path.write_text('{"retained":"first failure"}\n')
    second = _api.deepcopy(first)
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
    with _api.sqlite3.connect(self.root / "campaign.sqlite") as database:
        database.execute("CREATE TABLE dev12_campaigns (campaign_id TEXT, record TEXT)")
        database.execute(
            "INSERT INTO dev12_campaigns VALUES (?,?)",
            (campaign["campaign_id"], _api.json.dumps(campaign)),
        )
    checkpoint = {
        "passed_ids": [passed["id"]],
        "failed_id": base,
        "latest_failed_id": first_id,
        "last_campaign": campaign,
        "original_start_at": campaign["start_at"],
        "original_expires_at": campaign["expires_at"],
    }
    with _api.patch(
        "tools.gateway.evidence.dev12_completion_runner.continuation_checkpoint",
        return_value=checkpoint,
    ):
        self.assertEqual(self.check(second)["status"], "PASS", self.check(second)["errors"])
        receipt["plan_sha256"] = "0" * 64
        receipt_path.write_text(_api.json.dumps(receipt) + "\n")
        self.assertTrue(
            any("prior continuation receipt" in error for error in self.check(second)["errors"])
        )
        receipt["plan_sha256"] = _api.sha256(first_bytes).hexdigest()
        receipt_path.write_text(_api.json.dumps(receipt) + "\n")
        failed_path.unlink()
        self.assertTrue(
            any(
                "prior continuation failed evidence absent" in error
                for error in self.check(second)["errors"]
            )
        )
    return base, campaign, checkpoint, second


def _check_third_continuation_counters(_api, base, campaign, checkpoint, second, self):
    second_t47 = self.case(second, "t47_a")
    second_t47["evidence_paths"] = ["cases/" + second_t47["id"] + ".json"]
    second_t47["max_admissions"] = second_t47["max_possible_sends"] = 2
    second_bytes = (_api.json.dumps(second) + "\n").encode()
    (self.root / "plan.continuation2.json").write_bytes(second_bytes)
    second_receipt = {
        "plan_sha256": _api.sha256(second_bytes).hexdigest(),
        "source_tree": second["source_tree"],
        "case_count": len(second["cases"]),
    }
    (self.root / "preflight-receipt-continuation2.json").write_text(
        _api.json.dumps(second_receipt) + "\n"
    )
    third = _api.deepcopy(second)
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
    with _api.sqlite3.connect(self.root / "campaign.sqlite") as database:
        database.execute("UPDATE dev12_campaigns SET record=?", (_api.json.dumps(campaign),))
    checkpoint.update(
        passed_ids=passed_ids,
        failed_id=third_old_id,
        latest_failed_id=third_old_id,
        continuation_number=3,
        failed_attempt_ids=["python-attempt", "commonjs-attempt"],
        last_campaign=campaign,
    )
    with _api.patch(
        "tools.gateway.evidence.dev12_completion_runner.continuation_checkpoint",
        return_value=checkpoint,
    ):
        good = self.check(third)
        self.assertEqual(good["status"], "PASS", good["errors"])
        self.assertGreaterEqual(good["max_admissions"], 35)
        tampered = _api.deepcopy(third)
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
    return third


def _check_fourth_continuation_retained_attempts(_api, campaign, checkpoint, self, third):
    third_t49 = self.case(third, "t49_d")
    third_t49["evidence_paths"] = ["cases/" + third_t49["id"] + ".json"]
    third_t49["max_admissions"] = third_t49["max_possible_sends"] = 3
    third_bytes = (_api.json.dumps(third) + "\n").encode()
    (self.root / "plan.continuation3.json").write_bytes(third_bytes)
    (self.root / "preflight-receipt-continuation3.json").write_text(
        _api.json.dumps(
            {
                "plan_sha256": _api.sha256(third_bytes).hexdigest(),
                "source_tree": third["source_tree"],
                "case_count": len(third["cases"]),
            }
        )
        + "\n"
    )
    fourth = _api.deepcopy(third)
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
            fourth_id if value == fourth_old_id else value for value in case["late_dependencies"]
        ]
    fourth_passed = [case["id"] for case in third["cases"][:40]]
    for case in third["cases"][:40]:
        evidence_path = self.root / case["evidence_paths"][0]
        evidence_path.parent.mkdir(exist_ok=True)
        evidence_path.write_text('{"retained":"verified"}\n')
    t47_source = self.root / "cases/case.t47_a.composed.json"
    t47_ref = {
        "path": str(t47_source),
        "sha256": _api.sha256(t47_source.read_bytes()).hexdigest(),
        "bytes": t47_source.stat().st_size,
    }
    campaign.update(
        attempt_count=51, possible_send_count=51, cumulative_reserved_decimal="0.012200008"
    )
    with _api.sqlite3.connect(self.root / "campaign.sqlite") as database:
        database.execute("UPDATE dev12_campaigns SET record=?", (_api.json.dumps(campaign),))
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
    with _api.patch(
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
    return fourth, t47_ref, t47_source


def _check_fifth_continuation_retained_attempts(
    _api, campaign, checkpoint, fourth, self, t47_ref, t47_source
):
    fourth_t60 = self.case(fourth, "t60")
    fourth_t60["evidence_paths"] = ["cases/" + fourth_t60["id"] + ".json"]
    fourth_t60["max_admissions"] = fourth_t60["max_possible_sends"] = 3
    fourth_bytes = (_api.json.dumps(fourth) + "\n").encode()
    (self.root / "plan.continuation4.json").write_bytes(fourth_bytes)
    (self.root / "preflight-receipt-continuation4.json").write_text(
        _api.json.dumps(
            {
                "plan_sha256": _api.sha256(fourth_bytes).hexdigest(),
                "source_tree": fourth["source_tree"],
                "case_count": len(fourth["cases"]),
            }
        )
        + "\n"
    )
    fifth = _api.deepcopy(fourth)
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
    with _api.sqlite3.connect(self.root / "campaign.sqlite") as database:
        database.execute("UPDATE dev12_campaigns SET record=?", (_api.json.dumps(campaign),))
    t47_ref["sha256"] = _api.sha256(t47_source.read_bytes()).hexdigest()
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
    with _api.patch(
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
