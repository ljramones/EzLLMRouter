"""Prove that the wire matrix detects authentication and ownership bypasses."""

from copy import deepcopy
import io
import unittest
from unittest.mock import patch

from ezllmrouter_server.core import Coordinator
from ezllmrouter_server.wire_http.transport import WireTransport
from tests.unit.test_wire_authorization import WireAuthorizationTests


def run_case(method):
    case = WireAuthorizationTests(method)
    return unittest.TextTestRunner(stream=io.StringIO()).run(unittest.TestSuite([case]))


class WireAuthorizationSensitivityTests(unittest.TestCase):
    def test_the_matrix_detects_an_anonymous_authentication_bypass(self):
        method = "test_every_route_rejects_missing_invalid_duplicate_revoked_and_suspended_bearers"
        self.assertTrue(run_case(method).wasSuccessful())
        original = WireTransport._context
        observed = []

        def unsafe(handler):
            if not handler.headers.get_all("Authorization"):
                observed.append(handler.path)
                handler.selected_version = handler.headers["EzLLMRouter-Contract-Version"]
                coordinator = handler.application.coordinator
                return coordinator.authenticate(next(iter(coordinator.identity)))
            return original(handler)

        with patch.object(WireTransport, "_context", unsafe):
            result = run_case(method)
        self.assertFalse(result.wasSuccessful())
        self.assertFalse(result.errors)
        self.assertTrue(observed)
        self.assertEqual(result.testsRun, 1)

    def test_the_matrix_detects_a_cross_principal_result_disclosure(self):
        method = "test_active_identities_obey_independent_permissions_with_valid_bodies"
        self.assertTrue(run_case(method).wasSuccessful())
        original = Coordinator.status
        observed = []

        def unsafe(coordinator, submission_id, trusted):
            record = coordinator.store.get(submission_id)
            if record and record["work_key"]["principal_id"] != trusted["principal_id"]:
                observed.append(submission_id)
                trusted = deepcopy(trusted)
                trusted.update(
                    principal_id=record["work_key"]["principal_id"],
                    task_id=record["work_key"]["task_id"],
                )
            return original(coordinator, submission_id, trusted)

        with patch.object(Coordinator, "status", unsafe):
            result = run_case(method)
        self.assertFalse(result.wasSuccessful())
        self.assertFalse(result.errors)
        self.assertTrue(observed)
        self.assertEqual(result.testsRun, 1)
