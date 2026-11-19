"""Product plan implementation against independent A1 signature/context vectors."""
import base64
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
from duranki_server import successor_contract as contract  # noqa: E402
from duranki_server import successor_plan as plan_module  # noqa: E402

VECTORS = json.loads((ROOT / "tests/fixtures/contracts/dev12-successor-01/vectors.json").read_text())


class ProductPlanTests(unittest.TestCase):
    def test_adopted_signed_plan_and_independent_context(self):
        plan = VECTORS["plan_fixture"]["signed_plan"]
        example = next(x for x in VECTORS["examples"] if x["id"] == "DELEGATED_RERANK")
        context = VECTORS["execution_eligibility_context"]
        self.assertTrue(plan_module.verified_signature(plan, context["verification_keys"][0]))
        self.assertTrue(plan_module.execution_eligible(plan, example["request"],
                                                       example["canonical_work"],
                                                       example["admission_snapshot"], context))
        altered = deepcopy(plan)
        altered["execution_descriptor"]["timeout_ms"] = 5001
        self.assertFalse(plan_module.verified_signature(altered, context["verification_keys"][0]))
        self.assertFalse(plan_module.execution_eligible(altered, example["request"],
                                                        example["canonical_work"],
                                                        example["admission_snapshot"], context))
        revoked = deepcopy(context)
        revoked["verification_keys"][0]["eligibility"] = "revoked"
        self.assertFalse(plan_module.execution_eligible(plan, example["request"],
                                                        example["canonical_work"],
                                                        example["admission_snapshot"], revoked))
        rotated = deepcopy(context)
        rotated["active_minting_key"]["key_version"] = "v2"
        self.assertTrue(plan_module.execution_eligible(plan, example["request"],
                                                       example["canonical_work"],
                                                       example["admission_snapshot"], rotated))

    def test_fresh_synthetic_plan_full_binding(self):
        example = next(x for x in VECTORS["examples"] if x["id"] == "DELEGATED_RERANK")
        basis = VECTORS["execution_eligibility_context"]
        private = Ed25519PrivateKey.generate()
        plan = plan_module.mint_plan(example["request"], example["work_digest"],
                                     example["admission_snapshot_digest"], "submission.new",
                                     "attempt.new", "team.demo", "budget.new",
                                     basis["current_authority_revisions"],
                                     basis["expected_execution_context"],
                                     "synthetic.new.key", "v1", private)
        public_der = private.public_key().public_bytes(serialization.Encoding.DER,
                                                        serialization.PublicFormat.SubjectPublicKeyInfo)
        key = {"key_id": "synthetic.new.key", "key_version": "v1",
               "public_key_spki_base64": base64.b64encode(public_der).decode(),
               "eligibility": "eligible"}
        context = deepcopy(basis)
        context.update(expected_submission_id="submission.new", expected_attempt_id="attempt.new",
                       expected_reservation=plan["reservation"], verification_keys=[key],
                       active_minting_key={"key_id": "synthetic.new.key", "key_version": "v1"})
        self.assertTrue(contract.schema_valid(plan, contract.SCHEMAS["$defs"]["SignedPlan"]))
        self.assertTrue(plan_module.execution_eligible(plan, example["request"],
                                                       example["canonical_work"],
                                                       example["admission_snapshot"], context))
        wrong_scope = deepcopy(context)
        wrong_scope["expected_reservation"]["budget_account_id"] = "budget.other"
        self.assertFalse(plan_module.execution_eligible(plan, example["request"],
                                                        example["canonical_work"],
                                                        example["admission_snapshot"], wrong_scope))


if __name__ == "__main__":
    unittest.main()
