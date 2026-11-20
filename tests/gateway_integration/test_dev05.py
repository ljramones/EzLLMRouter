"""Local DEV-05 verifier and no-store fixture regressions."""

import json
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "verify_dev05", Path(__file__).with_name("verify_dev05.py")
)
verify_dev05 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify_dev05)


class Dev05Tests(unittest.TestCase):
    destination = {
        "configuration_ref": "cfg.demo",
        "service": "litellm.dev04",
        "endpoint": "127.0.0.1",
        "model": "model.demo",
        "model_version": "v1",
        "processing_region": "local",
    }

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)

    def write_one(self, name, value):
        (self.run / (name + ".stdout")).write_text(json.dumps(value) + "\n")

    def write_rows(self, name, values):
        (self.run / (name + ".stdout")).write_text(
            "".join(json.dumps(value) + "\n" for value in values)
        )

    def fixture(self):
        self.write_one("d05-readiness", 200)
        self.write_one("d05-python-package", {"version": "0.0.3"})
        self.write_one("d05-js-package", {"version": "0.0.2"})
        self.write_one("d05-worker-identities", {"selected_transport": "RelayTransport"})
        self.write_one(
            "d05-worker-isolation",
            {
                "network_mode": "none",
                "default_route": False,
                "trusted_code_mounted": False,
                "trusted_credentials_in_environment": False,
                "direct_receiver_connect_errno": 111,
            },
        )
        self.write_one(
            "d05-js-text",
            {
                "receiver_delta": 1,
                "submission_id": "submission.js",
                "candidate_id": "candidate.js",
                "attempt_id": "attempt.js",
                "served_destination": self.destination,
            },
        )
        self.write_one(
            "d05-python-cross-text",
            {
                "receiver_delta": 1,
                "cross_read": "submission.js",
                "cross_candidate_id": "candidate.js",
                "cross_attempt_id": "attempt.js",
                "submission_id": "submission.py",
                "candidate_id": "candidate.py",
                "attempt_id": "attempt.py",
                "served_destination": self.destination,
            },
        )
        self.write_one(
            "d05-js-cross-text",
            {
                "cross_read": "submission.py",
                "candidate_id": "candidate.py",
                "attempt_id": "attempt.py",
                "usage_state": "available",
                "provider_sends_delta": 0,
                "caller_tool_executions": 0,
            },
        )
        for name, step, sid, cid, aid in (
            (
                "d05-python-by-work-js-text",
                "step.dev04.js.text",
                "submission.js",
                "candidate.js",
                "attempt.js",
            ),
            (
                "d05-js-by-work-python-text",
                "step.dev04.python.text",
                "submission.py",
                "candidate.py",
                "attempt.py",
            ),
        ):
            self.write_one(
                name,
                {
                    "by_work": {"step_id": step, "execution_generation": "gen.1"},
                    "submission_id": sid,
                    "candidate_id": cid,
                    "attempt_id": aid,
                    "provider_sends_delta": 0,
                    "caller_tool_executions": 0,
                },
            )
        for actor, kind in (("python", "result_value"), ("js", "result_text")):
            self.write_one(
                "d05-" + actor + "-cycle",
                {
                    "result_kind": kind,
                    "provider_sends_delta": 2,
                    "caller_tool_executions": 1,
                    "first_submission_id": "submission." + actor + ".1",
                    "second_submission_id": "submission." + actor + ".2",
                    "first_attempt_id": "attempt." + actor + ".1",
                    "second_attempt_id": "attempt." + actor + ".2",
                    "first_candidate_id": "candidate." + actor + ".1",
                    "second_candidate_id": "candidate." + actor + ".2",
                    "call_id": "call.lookup.1",
                    "usage": [{"state": "available"}] * 2,
                    "destinations": [self.destination, self.destination],
                },
            )
            self.write_one(
                "d05-" + ("js-cross-python" if actor == "python" else "python-cross-js") + "-tool",
                {
                    "cross_read": "submission." + actor + ".1",
                    "candidate_id": "candidate." + actor + ".1",
                    "attempt_id": "attempt." + actor + ".1",
                    "usage_state": "available",
                    "provider_sends_delta": 0,
                    "caller_tool_executions": 0,
                },
            )
            self.write_one(
                "d05-"
                + ("js-by-work-python" if actor == "python" else "python-by-work-js")
                + "-tool",
                {
                    "by_work": {"step_id": "step.dev03." + actor, "execution_generation": "gen.1"},
                    "submission_id": "submission." + actor + ".1",
                    "candidate_id": "candidate." + actor + ".1",
                    "attempt_id": "attempt." + actor + ".1",
                    "provider_sends_delta": 0,
                    "caller_tool_executions": 0,
                },
            )
        roles = [
            ["system", "user"],
            ["system", "user"],
            ["system", "user"],
            ["system", "user", "assistant", "tool"],
            ["system", "user"],
            ["system", "user", "assistant", "tool"],
        ]
        arrivals = [
            {
                "attempt_id": "attempt." + str(i),
                "method": "POST",
                "body_sha256": "a" * 64,
                "body_bytes": 100,
                "message_roles": role,
                "model": "model.demo",
                "tool_call_ids": ["call.lookup.1"] if len(role) == 4 else [],
            }
            for i, role in enumerate(roles)
        ]
        receipts = [
            {
                "attempt_id": item["attempt_id"],
                "receipt": {
                    "method": "POST",
                    "body_sha256": "a" * 64,
                    "body_bytes": 100,
                    "timeout_seconds": {"connect": 1, "read": 1, "write": 1, "pool": 1},
                },
            }
            for item in arrivals
        ]
        self.write_rows("d05-checkpoint-receiver", arrivals)
        self.write_rows("d05-checkpoint-receipts", receipts)
        return arrivals, receipts

    def full_fixture(self):
        arrivals, receipts = self.fixture()
        for actor in ("python", "js"):
            self.write_one(
                "d05-" + actor + "-no-store",
                {
                    "variant": "live_no_store",
                    "provider_sends_delta": 2,
                    "caller_tool_executions": 1,
                    "forged_source_rejected": True,
                    "negative_stable_ms": 5200,
                    "candidate_access": ["not_retained", "not_retained"],
                    "destinations": [self.destination, self.destination],
                },
            )
        for mode, expected in (("503", "failed_after_transmit"), ("close", "outcome_unknown")):
            actor = {
                "receiver_delta": 1,
                "submission_id": "submission." + mode,
                "attempt_id": "attempt." + mode,
                "submission_state": expected,
                "usage_state": "not_recorded",
            }
            if mode == "503":
                actor.update(public_code="REMOTE_EXECUTION_FAILED", http_status=502)
            self.write_one("d05-" + mode, actor)
            self.write_one(
                "d05-js-cross-" + mode,
                {
                    "cross_read": actor["submission_id"],
                    "attempt_id": actor["attempt_id"],
                    "submission_state": expected,
                    "usage_state": "not_recorded",
                    "provider_sends_delta": 0,
                    "caller_tool_executions": 0,
                },
            )
            self.write_one("d05-" + mode + "-drain", {"submission_state": expected})
            (self.run / ("d05-" + mode + "-horizon.stdout")).write_text("5200\n")
        extra_roles = [
            ["system", "user"],
            ["system", "user", "assistant", "tool"],
            ["system", "user"],
            ["system", "user", "assistant", "tool"],
            ["system", "user"],
            ["system", "user"],
        ]
        for i, role in enumerate(extra_roles, 6):
            arrival = {
                "attempt_id": "attempt." + str(i),
                "method": "POST",
                "body_sha256": "a" * 64,
                "body_bytes": 100,
                "model": "model.demo",
                "message_roles": role,
                "tool_call_ids": ["call.lookup.1"] if len(role) == 4 else [],
            }
            arrivals.append(arrival)
            receipts.append(
                {
                    "attempt_id": arrival["attempt_id"],
                    "receipt": {
                        "method": "POST",
                        "body_sha256": "a" * 64,
                        "body_bytes": 100,
                        "timeout_seconds": {"connect": 1, "read": 1, "write": 1, "pool": 1},
                    },
                }
            )
        self.write_rows("d05-receiver", arrivals)
        self.write_rows("d05-receipts", receipts)
        events = [
            event
            for item in arrivals
            for event in (
                {"attempt_id": item["attempt_id"], "stage": "entered", "code": None},
                {"attempt_id": item["attempt_id"], "stage": "commit_acknowledged", "code": None},
                {
                    "attempt_id": item["attempt_id"],
                    "stage": "released_to_lower_transport",
                    "code": None,
                },
            )
        ]
        events.extend(
            [
                {"attempt_id": "attempt.mutation", "stage": "entered", "code": None},
                {"attempt_id": "attempt.mutation", "stage": "blocked", "code": "FDC_REJECTED"},
            ]
        )
        self.write_rows("d05-guard-events", events)
        sends = [
            {
                "attempt_id": item["attempt_id"],
                "first_acceptance_events": 1,
                "first_bytes_accepted_by_local_socket": True,
            }
            for item in arrivals
        ]
        sends.append(
            {
                "attempt_id": "attempt.mutation",
                "first_acceptance_events": 0,
                "first_bytes_accepted_by_local_socket": False,
            }
        )
        self.write_rows("d05-send-events", sends)
        self.write_rows(
            "d05-tool-mutation-events",
            [
                {
                    "attempt_id": "attempt.mutation",
                    "field": "tools[0].function.description",
                    "bound_sha256": "a" * 64,
                    "mutated_sha256": "b" * 64,
                    "same_length": True,
                }
            ],
        )
        store = [
            {
                "attempt_id": item["attempt_id"],
                "step_id": "step.other",
                "content_store_allowed": True,
                "candidate_present": True,
                "candidate_access": "present",
                "usage_state": "available",
            }
            for item in arrivals
        ]
        for i, step in zip(
            range(6, 10), ["step.dev03.no_store"] * 2 + ["step.dev03.js.no_store"] * 2
        ):
            store[i].update(
                step_id=step,
                content_store_allowed=False,
                candidate_present=False,
                candidate_access="not_retained",
            )
        store.append({"attempt_id": "attempt.mutation", "step_id": "step.dev03.mutation"})
        self.write_rows("d05-store-metadata", store)
        self.write_rows(
            "d05-authority-chain",
            [
                {
                    "attempt_id": row["attempt_id"],
                    "submission_id": "submission." + row["attempt_id"],
                    "step_id": row["step_id"],
                    "work_digest": "sha256:" + "c" * 64,
                    "intent": {
                        "attempt_id": row["attempt_id"],
                        "work_digest": "sha256:" + "c" * 64,
                        "plan_id": "plan." + row["attempt_id"],
                        "prepared_request_digest": "sha256:" + "d" * 64,
                    },
                    "receipt_plan_id": None
                    if row["step_id"] == "step.dev03.mutation"
                    else "plan." + row["attempt_id"],
                    "receipt_work_digest": None
                    if row["step_id"] == "step.dev03.mutation"
                    else "sha256:" + "c" * 64,
                    "usage_revisions": 0
                    if row["step_id"] == "step.dev03.mutation"
                    or row["attempt_id"] in ("attempt.10", "attempt.11")
                    else 1,
                }
                for row in store
            ],
        )
        self.write_one(
            "d05-worker-attempts", {"relay_attempt_counts": {row["attempt_id"]: 1 for row in store}}
        )
        self.write_one(
            "d05-no-store-storage",
            {
                "no_store_submissions": 4,
                "candidate_or_prompt_literals_present": False,
                "checked_rows": {
                    "submissions": 4,
                    "intents": 4,
                    "guard_dispatches": 4,
                    "usage_revisions": 4,
                },
            },
        )
        self.write_one("d05-log-scan", {"log_scan": "PASS"})
        self.write_one(
            "d05-tool-mutation",
            {
                "failure": "FDC_REJECTED",
                "provider_sends_delta": 0,
                "caller_tool_executions": 0,
                "negative_stable_ms": 5200,
            },
        )
        self.write_one("d05-raw-probe", {"error_type": "ConnectError"})
        self.write_one(
            "d05-forged-attempt",
            {"probe": "forged_sender_attempt", "rejected": True, "error_type": "ValueError"},
        )
        self.write_one("d05-probes-health", 200)
        (self.run / "d05-probes-horizon.stdout").write_text("5200\n")
        for name in (
            "d05-mutation-before",
            "d05-mutation-after",
            "d05-503-before-horizon",
            "d05-503-after-horizon",
            "d05-close-before-horizon",
            "d05-close-after-horizon",
        ):
            (self.run / (name + ".stdout")).write_text("stable\n")
        (self.run / "d05-probes-before.stdout").write_bytes(
            (self.run / "d05-receiver.stdout").read_bytes()
        )
        return arrivals, receipts

    def test_checkpoint_and_corrupted_final_receipt(self):
        arrivals, receipts = self.fixture()
        self.assertEqual(verify_dev05.checkpoint(self.run)["provider_arrivals"], 6)
        receipts[-1]["receipt"]["body_sha256"] = "b" * 64
        self.write_rows("d05-checkpoint-receipts", receipts)
        with self.assertRaises(AssertionError):
            verify_dev05.checkpoint(self.run)

    def test_missing_and_partial_evidence_fail(self):
        arrivals, _ = self.fixture()
        (self.run / "d05-js-cross-text.stdout").unlink()
        with self.assertRaises(FileNotFoundError):
            verify_dev05.checkpoint(self.run)
        self.write_one("d05-js-cross-text", {"cross_read": "submission.py"})
        with self.assertRaises(KeyError):
            verify_dev05.checkpoint(self.run)
        self.fixture()
        self.write_rows("d05-checkpoint-receiver", arrivals[:-1])
        with self.assertRaises(AssertionError):
            verify_dev05.checkpoint(self.run)

    def test_dev05_fixture_adds_only_trusted_no_store_lineage(self):
        root = Path(__file__).resolve().parents[2]
        baseline = json.loads((root / "tests/development_slice/fixture.json").read_text())
        dev05 = json.loads((root / "tests/gateway_integration/dev05_fixture.json").read_text())
        self.assertEqual(set(dev05) - set(baseline), set())
        self.assertEqual(
            dev05["trusted_source_labels"]["src.user.no_store"],
            {
                "lineage_ids": ["src.user.no_store"],
                "sensitivity": "confidential",
                "restrictions": ["no.content.store"],
            },
        )
        self.assertEqual(
            set(dev05["allowed_lineages"]) - set(baseline["allowed_lineages"]),
            {"src.user.no_store"},
        )

    def test_full_verifier_rejects_missing_and_corrupt_failure_evidence(self):
        self.full_fixture()
        self.assertEqual(verify_dev05.full(self.run)["provider_arrivals"], 12)
        (self.run / "d05-js-cross-503.stdout").unlink()
        with self.assertRaises(FileNotFoundError):
            verify_dev05.full(self.run)
        self.full_fixture()
        value = json.loads((self.run / "d05-js-cross-503.stdout").read_text())
        value["usage_state"] = "available"
        self.write_one("d05-js-cross-503", value)
        with self.assertRaises(AssertionError):
            verify_dev05.full(self.run)


if __name__ == "__main__":
    unittest.main()
