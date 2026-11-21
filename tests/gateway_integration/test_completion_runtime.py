"""CompletionRuntimeTests behaviour regressions."""

from __future__ import annotations

import unittest
from tests.gateway_integration.completion_preflight_support import CompletionPreflightFixture


class CompletionRuntimeTests(CompletionPreflightFixture, unittest.TestCase):
    def test_runtime_rejects_unexecuted_or_missing_observation(self):
        from tests.gateway_integration import test_completion_preflight as _api

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
                for error in _api.verify_case_result(case, nominal, self.root)["errors"]
            )
        )
        evidence = _api.Path(case["evidence_paths"][0])
        evidence.parent.mkdir(exist_ok=True)
        evidence.write_text('{"actual":"rejected"}\n')
        observation = {
            "stage": "ingress",
            "evidence_path": str(evidence),
            "sha256": _api.sha256(evidence.read_bytes()).hexdigest(),
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
                for error in _api.verify_case_result(case, nominal, self.root)["errors"]
            )
        )
        nominal["assertions"] = [
            {**row, "executed": True, "detail": "objective comparison with retained observation"}
            for row in nominal["assertions"]
        ]
        self.assertEqual(_api.verify_case_result(case, nominal, self.root)["status"], "PASS")

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
                for error in _api.verify_case_result(case, nominal, self.root)["errors"]
            )
        )

    def test_runtime_primary_outcome_and_rejection_are_independent(self):
        from tests.gateway_integration import test_completion_preflight as _api

        case = self.case(self.plan, "t01")
        path = _api.Path(case["evidence_paths"][0])
        path.parent.mkdir(exist_ok=True)
        path.write_text('{"observed":"primary"}\n')
        digest = _api.sha256(path.read_bytes()).hexdigest()
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
            _api.verify_case_result(
                case, result, self.root, actual=independent, require_actual=True
            )["status"],
            "PASS",
        )
        self.assertTrue(
            any(
                "runtime facts missing" in error
                for error in _api.verify_case_result(case, result, self.root, require_actual=True)[
                    "errors"
                ]
            )
        )
        changed = dict(independent, terminal_status="unknown")
        self.assertTrue(
            any(
                "terminal state differs" in error
                for error in _api.verify_case_result(case, result, self.root, actual=changed)[
                    "errors"
                ]
            )
        )
        over_allocated = dict(independent, reservation_delta_decimal="0.010000001")
        self.assertTrue(
            any(
                "USD reservation allocation" in error
                for error in _api.verify_case_result(
                    case, result, self.root, actual=over_allocated
                )["errors"]
            )
        )
        rejected = _api.deepcopy(case)
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
            _api.verify_case_result(
                rejected, result, self.root, actual=stopped, require_actual=True
            )["status"],
            "PASS",
        )
        leaked = dict(
            stopped, primary_stages=["ingress", "admission", "guard", "first_write", "receiver"]
        )
        self.assertTrue(
            any(
                "forbidden later stage" in error
                for error in _api.verify_case_result(rejected, result, self.root, actual=leaked)[
                    "errors"
                ]
            )
        )
        wrong_code = dict(stopped, rejection={**stopped["rejection"], "code": "OTHER_REJECTION"})
        self.assertTrue(
            any(
                "rejection differs" in error
                for error in _api.verify_case_result(
                    rejected, result, self.root, actual=wrong_code
                )["errors"]
            )
        )
        delivery_failure = _api.deepcopy(case)
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
            _api.verify_case_result(
                delivery_failure, result, self.root, actual=failed_with_charge, require_actual=True
            )["status"],
            "PASS",
        )

    def test_offline_client_artifacts_do_not_replace_live_client_coverage(self):
        from tests.gateway_integration import test_completion_preflight as _api

        plan = _api.deepcopy(self.plan)
        for case in plan["cases"]:
            if case["max_possible_sends"]:
                case["installed_client_mode"] = "none"
        result = self.check(plan)
        self.assertTrue(
            any("absent from fresh target submissions" in error for error in result["errors"])
        )

    def test_rejection_metadata_and_evidence_sources_must_be_precise(self):
        from tests.gateway_integration import test_completion_preflight as _api

        self.assertEqual(
            _api._fixture_path_for_scenario("t03"),
            _api.Path(_api.__file__).resolve().parents[2] / "tests/development_slice/request.json",
        )
        plan = _api.deepcopy(self.plan)
        case = self.case(plan, "t01")
        case["expected_rejection"] = {"stage": "ingress", "code": "bad code", "http_status": True}
        self.assertTrue(
            any("terminal/rejection expectation" in error for error in self.check(plan)["errors"])
        )
        wrong_fixture = _api.deepcopy(self.plan)
        self.case(wrong_fixture, "t48_a")["fixture"] = {
            "path": str(_api.Path(_api.__file__)),
            "sha256": _api.sha256(_api.Path(_api.__file__).read_bytes()).hexdigest(),
        }
        self.assertTrue(
            any(
                "fixture is not the fixed scenario input" in error
                for error in self.check(wrong_fixture)["errors"]
            )
        )
        wrong_build = _api.deepcopy(self.plan)
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
