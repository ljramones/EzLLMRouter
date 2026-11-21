"""The authorization gate must detect a deliberately permitted read-only mutation."""

import io
import unittest
from unittest.mock import patch

from ezllmrouter_server.operator_http.accounts import AccountsRoutes
from tests.operator_console.test_authorization_matrix import AuthorizationMatrixTests, POLICY


class AuthorizationGateSensitivityTests(unittest.TestCase):
    def test_policy_requires_readonly_password_and_valid_mutation_cases(self):
        self.assertIn("read_only_status", POLICY["columns"])
        self.assertIn("password_change_status", POLICY["columns"])
        expected = {
            method + " " + registered
            for method, registered, *_ in POLICY["routes"]
            if method != "GET"
        }
        self.assertEqual(set(POLICY["valid_mutations"]), expected)
        for key, row in POLICY["valid_mutations"].items():
            self.assertIn("body", row)
            if key != "POST /operator/v1/logout":
                self.assertTrue(row["body"], key)

    def test_a_readonly_mutation_bypass_makes_the_role_matrix_fail(self):
        original = AccountsRoutes.post_operator_v1_users
        observed = []

        def unsafe(handler, path, session, body, scope):
            if session[1]["role"] == "read_only_operator" and handler.path == "/operator/v1/users":
                observed.append(handler.path)
                return handler._send(200, {"unsafe": True})
            return original(handler, path, session, body, scope)

        baseline = AuthorizationMatrixTests(
            "test_admin_and_ordinary_route_results_match_reviewed_expectations"
        )
        baseline_result = unittest.TextTestRunner(stream=io.StringIO()).run(
            unittest.TestSuite([baseline])
        )
        self.assertTrue(
            baseline_result.wasSuccessful(), "the unmodified role matrix must pass first"
        )
        case = AuthorizationMatrixTests(
            "test_admin_and_ordinary_route_results_match_reviewed_expectations"
        )
        with patch.object(AccountsRoutes, "post_operator_v1_users", unsafe):
            result = unittest.TextTestRunner(stream=io.StringIO()).run(unittest.TestSuite([case]))
        self.assertFalse(
            result.wasSuccessful(), "the matrix passed after a read-only mutation was permitted"
        )
        self.assertTrue(observed, "the matrix never exercised a read-only mutation")
        self.assertEqual(result.testsRun, 1)

    def test_the_valid_body_matrix_detects_a_body_dependent_readonly_bypass(self):
        original = AccountsRoutes.post_operator_v1_users
        observed = []

        def unsafe(handler, path, session, body, scope):
            if (
                session[1]["role"] == "read_only_operator"
                and body.get("username") == "matrix.created"
            ):
                observed.append(body)
                return handler._send(201, {"unsafe": True})
            return original(handler, path, session, body, scope)

        case = AuthorizationMatrixTests(
            "test_valid_mutation_bodies_are_denied_without_changes_for_nonwriters"
        )
        with patch.object(AccountsRoutes, "post_operator_v1_users", unsafe):
            result = unittest.TextTestRunner(stream=io.StringIO()).run(unittest.TestSuite([case]))
        self.assertFalse(
            result.wasSuccessful(), "empty-body requests missed the body-dependent bypass"
        )
        self.assertTrue(observed)
