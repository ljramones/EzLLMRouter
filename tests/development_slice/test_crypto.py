"""Container-only Ed25519 plan path check; does not print key material."""
import base64
import copy
import json
import unittest
import threading
import time
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ezllmrouter_server.canonical import ContractError, digest, jcs, projection, validate_text_request, work_digest
from ezllmrouter_server.core import Coordinator
from ezllmrouter_server.plans import PlanAuthority
from ezllmrouter_server.store import SQLiteStore
from recipe import SyntheticDevelopmentRecipe, SyntheticTextRecipe



class SignedPlanTests(unittest.TestCase):
    def test_signed_frame_and_no_store_output(self):
        base = Path(__file__).parent
        fixture = json.loads((base / "fixture.json").read_text())
        request = json.loads((base / "request.json").read_text())
        trusted = fixture["trusted_context"]
        messages, settings, deadline, pd = validate_text_request(request, trusted, fixture["destination"],
            fixture["prompt_blocks"], fixture["allowed_lineages"])
        projected = projection(request, trusted, fixture["destination"], messages, settings, deadline, pd)
        wd = work_digest(projected)
        key = {"principal_id": trusted["principal_id"], "task_id": request["task_id"],
               "step_id": request["step_id"], "step_revision": request["step_revision"],
               "execution_generation": request["execution_generation"]}
        private_key = Ed25519PrivateKey.generate()
        authority = PlanAuthority(private_key, fixture["policy"])
        plan = authority.issue(projected, wd, key, fixture["classification"], fixture["retention"])
        authority.verify(plan, wd, fixture["policy"]["policy_version"])
        envelope = plan["signature_envelope"]
        unsigned = {k: v for k, v in plan.items() if k != "signature_envelope"}
        assert envelope["signed_plan_digest"] == digest(jcs(unsigned))
        oracle = ("ezllmrouter-plan-v0.2\nEd25519\n" + fixture["policy"]["key_id"] + "\n" +
                  fixture["policy"]["key_version"] + "\n" + envelope["signed_plan_digest"]).encode()
        signature = base64.urlsafe_b64decode(envelope["signature"] + "=" * (-len(envelope["signature"]) % 4))
        private_key.public_key().verify(signature, oracle)
        # Independently signed adopted frame must also be consumed by the implementation.
        other = {**plan, "signature_envelope": {**envelope,
            "signature": base64.urlsafe_b64encode(private_key.sign(oracle)).decode().rstrip("=")}}
        authority.verify(other, wd, fixture["policy"]["policy_version"])
        for mutation in ["work_digest", "configuration_ref"]:
            altered = dict(plan)
            altered[mutation] = "sha256:" + "0" * 64 if mutation == "work_digest" else "cfg.other"
            try:
                authority.verify(altered, wd, fixture["policy"]["policy_version"])
            except ContractError as exc:
                assert exc.code == "PLAN_INVALID_OR_STALE"
            else:
                raise AssertionError("tampered plan accepted")
        for field in ["key_id", "key_version", "signed_plan_digest"]:
            changed = {**plan, "signature_envelope": {**envelope, field: "changed"}}
            try:
                authority.verify(changed, wd, fixture["policy"]["policy_version"])
            except ContractError as exc:
                assert exc.code == "PLAN_INVALID_OR_STALE"
            else:
                raise AssertionError("framing field tamper accepted: " + field)
        for field in ["policy_version", "registry_version", "recovery_policy_version", "adapter_version",
                      "quality_approval_ref", "adapter_recipe_ref", "decision_record_ref", "limit_ref",
                      "limit_version", "max_attempt_charge_decimal", "currency", "alert_policy_ref"]:
            original = authority.policy[field]
            authority.policy[field] = "changed"
            try:
                authority.verify(plan, wd, authority.policy["policy_version"])
            except ContractError as exc:
                assert exc.code == "PLAN_INVALID_OR_STALE"
            else:
                raise AssertionError("current authority drift accepted: " + field)
            finally:
                authority.policy[field] = original

        class SyntheticAdapter:
            def __init__(self): self.sent = []
            def prepare(self, body):
                return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
            def describe(self, prepared, timeout_ms, destination):
                import hashlib
                return {"method": "POST", "url": "http://receiver:8766/v1/chat/completions",
                        "content_type": "application/json", "content_length": len(prepared),
                        "body_sha256": hashlib.sha256(prepared).hexdigest(), "timeout_ms": timeout_ms,
                        "processing_region": destination["processing_region"]}
            def send(self, prepared, timeout_ms, expected):
                self.sent.append(prepared)
                return {"status": 200, "body": {"text": "Hello."}}

        for changed in (True, False):
            store = SQLiteStore(":memory:")
            current = copy.deepcopy(trusted)
            adapter = SyntheticAdapter()
            coordinator = Coordinator(store, {"token.synthetic": current}, copy.deepcopy(fixture["destination"]),
                fixture["prompt_blocks"], fixture["allowed_lineages"],
                PlanAuthority(Ed25519PrivateKey.generate(), copy.deepcopy(fixture["policy"])), adapter,
                copy.deepcopy(fixture["retention"]), copy.deepcopy(fixture["classification"]),
                SyntheticTextRecipe())
            gate = threading.Event()
            blockers = [coordinator.pool.submit(gate.wait, 3) for _ in range(4)]
            try:
                code, reply = coordinator.submit(request, current, 0, "token.synthetic")
                assert code == 202
                sid = reply["handle"]["submission_id"]
                current["expires_at"] = "2099-01-01T00:00:00Z"
                if changed: current["charging_owner_id"] = "owner.changed"
            finally:
                gate.set()
                for blocker in blockers: blocker.result(timeout=3)
            for _ in range(100):
                if store.get(sid)["submission_state"] in ("completed", "failed_before_transmit"): break
                time.sleep(0.01)
            assert store.get(sid)["submission_state"] == ("failed_before_transmit" if changed else "completed")
            assert len(adapter.sent) == (0 if changed else 1)
            coordinator.pool.shutdown(wait=True)
            store.close()

        class CapturingPlanAuthority(PlanAuthority):
            def __init__(self, private_key, policy):
                super().__init__(private_key, policy)
                self.plans = []
            def issue(self, *args):
                plan = super().issue(*args)
                self.plans.append(plan)
                return plan

        restricted = copy.deepcopy(request)
        restricted.update(step_id="step.restricted.crypto", requested_features=["text", "tools"],
                          tool_definitions=[{"name": "lookup", "description": "Synthetic lookup",
                                             "input_schema": {"type": "object", "properties": {"key": {"type": "string"}},
                                                              "required": ["key"]}}], tool_choice="auto")
        restricted_label = {"lineage_ids": ["src.user.1"], "sensitivity": "confidential",
                            "restrictions": ["no.content.store"]}
        restricted["messages"][1]["blocks"][0]["source_labels"] = restricted_label
        trusted_labels = copy.deepcopy(fixture["trusted_source_labels"])
        trusted_labels["src.user.1"] = restricted_label
        store = SQLiteStore(":memory:")
        adapter = SyntheticAdapter()
        authority = CapturingPlanAuthority(Ed25519PrivateKey.generate(), copy.deepcopy(fixture["policy"]))
        coordinator = Coordinator(store, {"token.synthetic": copy.deepcopy(trusted)},
            copy.deepcopy(fixture["destination"]), fixture["prompt_blocks"], fixture["allowed_lineages"],
            authority, adapter, copy.deepcopy(fixture["retention"]), copy.deepcopy(fixture["classification"]),
            SyntheticDevelopmentRecipe(), trusted_source_labels=trusted_labels)
        try:
            code, reply = coordinator.submit(restricted, trusted, 3000, "token.synthetic")
            assert code == 200 and reply["state"] == "delivered" and len(adapter.sent) == 1
            signed = authority.plans[-1]
            authority.verify(signed, signed["work_digest"], authority.policy["policy_version"])
            assert signed["classification_snapshot"]["combined_restrictions"] == ["no.content.store"]
            assert signed["effective_retention"]["content_store_allowed"] is False
            assert reply["candidate"]["output_blocks"][0]["source_labels"] == {
                "lineage_ids": ["src.candidate.synthetic"], "sensitivity": "confidential",
                "restrictions": ["no.content.store"]}
            status = coordinator.status(reply["handle"]["submission_id"], trusted)
            assert status["candidate_access"] == "not_retained" and "candidate" not in status
        finally:
            coordinator.pool.shutdown(wait=True)
            store.close()
        print("PASS: adopted Ed25519 frame, queued scope and signed source handling with no-store output")


if __name__ == "__main__":
    unittest.main()
