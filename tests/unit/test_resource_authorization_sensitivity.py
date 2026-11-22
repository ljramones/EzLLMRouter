"""Require the resource matrix to catch real scope and mutation bypasses."""

import io
import unittest
from unittest.mock import patch

from ezllmrouter_server.integration_accounting import ExternalAccounting
from ezllmrouter_server.operator_http.accounts import AccountsRoutes
from tests.operator_console.test_resource_authorization import ResourceAuthorizationTests


def run_case(method):
    return unittest.TextTestRunner(stream=io.StringIO()).run(
        unittest.TestSuite([ResourceAuthorizationTests(method)])
    )


class ResourceAuthorizationSensitivityTests(unittest.TestCase):
    def test_the_matrix_detects_an_administrator_cross_dataset_read_bypass(self):
        method = "test_existing_reads_obey_roles_owners_and_console_modes"
        self.assertTrue(run_case(method).wasSuccessful())
        original = ExternalAccounting._authorize
        observed = []

        def unsafe(ledger, principal, dataset, action):
            if (
                principal["role"] == "registry_admin"
                and principal["principal_id"] != dataset["owner_id"]
            ):
                observed.append((dataset["dataset_id"], action))
                return None
            return original(ledger, principal, dataset, action)

        with patch.object(ExternalAccounting, "_authorize", unsafe):
            result = run_case(method)
        self.assertFalse(result.wasSuccessful())
        self.assertFalse(result.errors)
        self.assertTrue(observed)
        self.assertEqual(result.testsRun, 1)

    def test_the_matrix_detects_a_valid_body_readonly_connector_mutation(self):
        method = "test_valid_family_mutations_are_denied_without_any_side_effect"
        self.assertTrue(run_case(method).wasSuccessful())
        original = AccountsRoutes.post_operator_v1_local_connectors
        observed = []

        def unsafe(handler, path, session, body, scope):
            if (
                session[1]["role"] == "read_only_operator"
                and handler.path.endswith("/models")
                and body.get("enabled") is True
            ):
                connector_id = handler.path[len("/operator/v1/local-connectors/") : -len("/models")]
                result = handler._connectors.configure("owner.local", connector_id, body)
                observed.append(result["revision"])
                return handler._send(200, result)
            return original(handler, path, session, body, scope)

        with patch.object(AccountsRoutes, "post_operator_v1_local_connectors", unsafe):
            result = run_case(method)
        self.assertFalse(result.wasSuccessful())
        self.assertFalse(result.errors)
        self.assertTrue(observed)
        self.assertEqual(result.testsRun, 1)
