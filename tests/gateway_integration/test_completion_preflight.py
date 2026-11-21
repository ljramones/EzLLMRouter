"""No-send controls for the fixed DEV-12 Completion 02 scenario gate."""

from __future__ import annotations

from copy import deepcopy as deepcopy
from hashlib import sha256 as sha256
from pathlib import Path as Path
from tempfile import TemporaryDirectory as TemporaryDirectory
from types import SimpleNamespace as SimpleNamespace
from unittest.mock import patch as patch
import json as json
import os as os
import sqlite3 as sqlite3
import sys as sys
import unittest as unittest

from tools.gateway.evidence.dev12_completion_catalog import (
    CaseHandler as CaseHandler,
    REQUIRED_PAIRS as REQUIRED_PAIRS,
    SCENARIOS as SCENARIOS,
)
from tools.gateway.evidence.dev12_completion_preflight import (
    _fixture_path_for_scenario as _fixture_path_for_scenario,
    main as main,
    mounted_source_identity as mounted_source_identity,
    validate as validate,
    verify_case_result as verify_case_result,
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


from tests.gateway_integration.completion_preflight_support import CompletionPreflightFixture


class CompletionPreflightTests(CompletionPreflightFixture, unittest.TestCase):
    def test_complete_catalog_is_repeatable_without_sending(self):
        from tests.gateway_integration import test_completion_preflight as _api

        first = self.check()
        self.assertEqual(first["status"], "PASS", first["errors"])
        self.assertEqual(first["case_count"], len(_api.REQUIRED_PAIRS))
        self.assertEqual(self.check()["status"], "PASS")

    def test_all_labels_one_nominal_case_or_copies_fail(self):
        from tests.gateway_integration import test_completion_preflight as _api

        one = _api.deepcopy(self.plan)
        one["cases"] = [one["cases"][0]]
        one["cases"][0]["assurance_ids"] = sorted(
            label for spec in _api.SCENARIOS.values() for label in spec.assurance_ids
        )
        self.assertTrue(
            any("fixed scenario/variant" in error for error in self.check(one)["errors"])
        )
        copies = _api.deepcopy(self.plan)
        copies["cases"] = [
            {**_api.deepcopy(copies["cases"][0]), "id": f"copy.{n}"} for n in range(66)
        ]
        self.assertTrue(
            any("duplicate scenario/variant" in error for error in self.check(copies)["errors"])
        )

    def test_missing_handler_changed_source_and_nominal_result_fail(self):
        from tests.gateway_integration import test_completion_preflight as _api

        handlers = dict(self.handlers)
        handlers.pop("ingress_identity")
        self.assertEqual(self.check(handlers=handlers)["status"], "BLOCKED_NO_SEND")
        changed = _api.deepcopy(self.plan)
        self.case(changed, "t01")["handler_source_sha256"] = "0" * 64
        self.assertTrue(
            any("source identity mismatch" in error for error in self.check(changed)["errors"])
        )
        self.assertEqual(
            _api.verify_case_result(
                self.plan["cases"][0], _api.nominal_file_exists(None, None), self.root
            )["status"],
            "FAIL",
        )

    def test_recovery_chain_missing_or_nominal_dependencies_fail(self):
        from tests.gateway_integration import test_completion_preflight as _api

        missing = _api.deepcopy(self.plan)
        missing["cases"] = [
            case
            for case in missing["cases"]
            if not (case["scenario_id"] == "recovery_chain" and case["variant"] == "unknown_pause")
        ]
        self.assertTrue(
            any("recoverable unknown" in error for error in self.check(missing)["errors"])
        )
        nominal = _api.deepcopy(self.plan)
        self.case(nominal, "recovery_chain", "retained_receipt")["prerequisites"] = []
        self.case(nominal, "recovery_chain", "eligible_resume")["late_dependencies"] = []
        errors = self.check(nominal)["errors"]
        self.assertTrue(any("recovery chain lacks" in error for error in errors))
        self.assertTrue(any("audited resume lacks actual late append" in error for error in errors))

    def test_cycle_identity_capture_and_mixed_budget_fail(self):
        from tests.gateway_integration import test_completion_preflight as _api

        plan = _api.deepcopy(self.plan)
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
        from tests.gateway_integration import test_completion_preflight as _api

        plan = _api.deepcopy(self.plan)
        self.case(plan, "t60")["max_admissions"] = 1
        self.case(plan, "t60")["max_possible_sends"] = 1
        self.assertTrue(
            any("fixed scenario minimum" in error for error in self.check(plan)["errors"])
        )
        unallocated = _api.deepcopy(self.plan)
        self.case(unallocated, "t60")["max_exposure_decimal"] = "0.000000000"
        self.assertTrue(
            any(
                "lacks a finite exposure allocation" in error
                for error in self.check(unallocated)["errors"]
            )
        )

    def test_only_terminal_imported_underbound_may_have_zero_receiver_send(self):
        from tests.gateway_integration import test_completion_preflight as _api

        historical = self.case(self.plan, "t50_e")
        self.assertEqual((historical["max_admissions"], historical["max_possible_sends"]), (0, 0))
        self.assertEqual(self.check()["status"], "PASS")
        ordinary = _api.deepcopy(self.plan)
        self.case(ordinary, "t49_e")["max_admissions"] = 0
        self.case(ordinary, "t49_e")["max_possible_sends"] = 0
        errors = self.check(ordinary)["errors"]
        self.assertTrue(
            any("receiver case lacks a possible-send bound" in error for error in errors)
        )

    def test_populated_reporting_requires_actual_prior_cases(self):
        from tests.gateway_integration import test_completion_preflight as _api

        plan = _api.deepcopy(self.plan)
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
        from tests.gateway_integration import test_completion_preflight as _api

        plan = _api.deepcopy(self.plan)
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
        from tests.gateway_integration import test_completion_preflight as _api

        plan = _api.deepcopy(self.plan)
        self.case(plan, "t01")["id"] = "../outside"
        self.assertTrue(
            any("duplicate/invalid case ID" in error for error in self.check(plan)["errors"])
        )
