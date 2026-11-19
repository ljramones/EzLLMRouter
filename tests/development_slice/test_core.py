"""Pure domain/store tests; no acquired package import or network."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
sys.path.insert(0, str(ROOT / "tests/development_slice"))
from duranki_server.canonical import ContractError, jcs, projection, strict_loads, validate_text_request, work_digest
from duranki_server.core import Coordinator, usage_revision
from duranki_server.store import SQLiteStore
from recipe import SyntheticTextRecipe

VECTORS = json.loads((ROOT / "tests/fixtures/contracts/wp-a-03-c01/DURANKI-WP-A-VECTORS-v0.3-CORRECTION-01.json").read_text())
FIXTURE = json.loads((ROOT / "tests/development_slice/fixture.json").read_text())
REQUEST = json.loads((ROOT / "tests/development_slice/request.json").read_text())


def patched(base, operations):
    item = copy.deepcopy(base)
    for op in operations:
        parts = [p.replace("~1", "/").replace("~0", "~") for p in op["path"].split("/")[1:]]
        parent = item
        for part in parts[:-1]:
            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        key = int(parts[-1]) if isinstance(parent, list) and parts[-1] != "-" else parts[-1]
        if op["op"] == "remove":
            del parent[key]
        elif op["op"] == "replace":
            parent[key] = copy.deepcopy(op["value"])
        elif op["op"] == "add":
            if isinstance(parent, list):
                parent.insert(len(parent) if key == "-" else key, copy.deepcopy(op["value"]))
            else:
                parent[key] = copy.deepcopy(op["value"])
        else:
            raise AssertionError(op)
    return item


def wait_future_release(coordinator, submission_id):
    for _ in range(100):
        with coordinator._futures_lock:
            if submission_id not in coordinator._futures:
                return
        time.sleep(0.01)
    raise AssertionError("terminal Future remained reachable")


class FakeAuthority:
    policy = {"policy_version": "policy.dev01"}
    def issue(self, projection, digest, key, classification, retention):
        return {"plan_id": "plan.test", "work_digest": digest, "work_key": copy.deepcopy(key),
                "destination": copy.deepcopy(projection["destination"]),
                "classification_snapshot": copy.deepcopy(classification),
                "effective_retention": copy.deepcopy(retention), "deadline": projection["work"]["deadline"],
                "per_attempt_total_timeout_ms": 1000}
    def verify(self, plan, digest, policy):
        assert plan["work_digest"] == digest and policy == "policy.dev01"


class FakeAdapter:
    def __init__(self, status=200, body=None, delay=0, unknown=False):
        self.sent = []
        self.status = status
        self.body = body if body is not None else {"text": "Hello.", "usage": {"input_tokens": 3, "output_tokens": 1}}
        self.delay = delay
        self.unknown = unknown
    def prepare(self, body):
        return json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
    def describe(self, prepared, timeout_ms, destination):
        return {"method": "POST", "url": "http://receiver:8766/v1/chat/completions",
                "content_type": "application/json", "content_length": len(prepared),
                "body_sha256": hashlib.sha256(prepared).hexdigest(),
                "timeout_ms": timeout_ms, "processing_region": destination["processing_region"]}
    def send(self, prepared, timeout_ms, expected):
        assert self.describe(prepared, timeout_ms, FIXTURE["destination"]) == expected
        self.sent.append(prepared)
        if self.delay: time.sleep(self.delay)
        if self.unknown: raise OSError("ambiguous")
        return {"status": self.status, "body": self.body}


class HeldAdapter(FakeAdapter):
    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()
    def send(self, prepared, timeout_ms, expected):
        self.entered.set()
        if not self.release.wait(3): raise AssertionError("held adapter was not released")
        return super().send(prepared, timeout_ms, expected)


class FailIntentStore:
    def __init__(self, inner): self.inner = inner
    def __getattr__(self, name): return getattr(self.inner, name)
    def intent(self, *_args): raise OSError("injected commit failure")


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = SQLiteStore(Path(self.tmp.name) / "dev.sqlite")
        self.addCleanup(self.store.close)
        self.adapter = FakeAdapter()
        self.trusted = FIXTURE["trusted_context"]

    def coordinator(self, store=None, adapter=None, retention=None, faults=None):
        c = Coordinator(store or self.store, {"token.synthetic": self.trusted}, copy.deepcopy(FIXTURE["destination"]),
                        FIXTURE["prompt_blocks"], FIXTURE["allowed_lineages"], FakeAuthority(),
                        adapter or self.adapter, copy.deepcopy(retention or FIXTURE["retention"]),
                        copy.deepcopy(FIXTURE["classification"]),
                        SyntheticTextRecipe(), faults)
        self.addCleanup(c.pool.shutdown, wait=True)
        return c

    def test_all_adopted_work_goldens(self):
        for golden in VECTORS["golden"]:
            with self.subTest(golden=golden["id"]):
                path = golden["instance_ref"].split(".")
                value = VECTORS[path[0]][path[1]]
                value = patched(value, golden.get("patch", []))
                self.assertEqual(jcs(value).decode(), golden["canonical_json"])
                self.assertEqual(work_digest(value), golden["sha256_domain_digest"])

    def test_request_projection_from_trusted_inputs(self):
        messages, settings, deadline, pd = validate_text_request(
            REQUEST, self.trusted, FIXTURE["destination"], FIXTURE["prompt_blocks"], FIXTURE["allowed_lineages"])
        result = projection(REQUEST, self.trusted, FIXTURE["destination"], messages, settings, deadline, pd)
        self.assertEqual(result["trusted"]["principal_id"], "svc.demo")
        self.assertEqual(result["work"]["resolved_prompt"]["resolved_digest"],
                         VECTORS["examples"]["canonical_text"]["work"]["resolved_prompt"]["resolved_digest"])
        prepared = self.coordinator()._prepared(result)
        self.assertEqual(prepared, VECTORS["prepared_request_utf8"].encode())

    def test_strict_json_and_semantic_negatives(self):
        for raw in [b'{"a":1,"a":2}', b'{"x":1.5}', b'{"x":NaN}', b'{"x":-0}', b'{"x":"\\ud800"}']:
            with self.subTest(raw=raw), self.assertRaises(ContractError): strict_loads(raw)
        bad = copy.deepcopy(REQUEST); bad["requested_features"] = ["tools"]
        with self.assertRaises(ContractError) as raised:
            validate_text_request(bad, self.trusted, FIXTURE["destination"], FIXTURE["prompt_blocks"], FIXTURE["allowed_lineages"])
        self.assertEqual(raised.exception.code, "SEMANTIC_INVALID")
        bad = copy.deepcopy(REQUEST); bad["requested_features"] = [{"text": True}]
        with self.assertRaises(ContractError) as raised:
            validate_text_request(bad, self.trusted, FIXTURE["destination"], FIXTURE["prompt_blocks"], FIXTURE["allowed_lineages"])
        self.assertEqual(raised.exception.code, "SCHEMA_INVALID")
        bad = copy.deepcopy(REQUEST); bad["messages"][0]["blocks"][0]["text"] = "Forged prompt"
        with self.assertRaises(ContractError):
            validate_text_request(bad, self.trusted, FIXTURE["destination"], FIXTURE["prompt_blocks"], FIXTURE["allowed_lineages"])

    def test_roundtrip_status_and_restart(self):
        self.assertEqual(self.store.db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(self.store.db.execute("PRAGMA synchronous").fetchone()[0], 2)
        c = self.coordinator()
        status, reply = c.submit(REQUEST, self.trusted, 1000)
        self.assertEqual((status, reply["state"]), (200, "delivered"))
        sid = reply["handle"]["submission_id"]
        self.assertEqual(len(self.adapter.sent), 1)
        self.assertEqual(c.status_by_work(reply["handle"]["work_key"], self.trusted)["handle"], reply["handle"])
        snapshot = c.status(sid, self.trusted)
        self.assertEqual(snapshot["candidate"]["candidate_id"], reply["candidate"]["candidate_id"])
        self.assertEqual(len(self.adapter.sent), 1)
        other = SQLiteStore(Path(self.tmp.name) / "dev.sqlite")
        try:
            self.assertEqual(other.get(sid)["submission_state"], "completed")
            self.assertEqual(other.intent_count(sid), 1)
        finally:
            other.close()

    def test_unauthorized_and_mutated_never_send(self):
        c = self.coordinator(faults={"mutate_after_binding": lambda b: b.replace(b'"model":"model.demo"', b'"model":"model.other"')})
        with self.assertRaises(ContractError): c.authenticate("not-a-token")
        status, reply = c.submit(REQUEST, self.trusted)
        self.assertEqual((status, reply["error"]["code"]), (409, "FDC_REJECTED"))
        self.assertEqual(self.adapter.sent, [])
        self.assertEqual(self.store.intent_count(reply["handle"]["submission_id"]), 0)

    def test_intent_commit_failure_never_sends(self):
        c = self.coordinator(store=FailIntentStore(self.store))
        status, reply = c.submit(REQUEST, self.trusted)
        self.assertEqual((status, reply["error"]["code"]), (503, "INTENT_PERSIST_FAILED"))
        self.assertEqual(self.adapter.sent, [])
        self.assertEqual(self.store.intent_count(reply["handle"]["submission_id"]), 0)

    def test_no_store_wait_expiry(self):
        adapter = FakeAdapter(delay=0.05)
        retention = {"retention_class": "no_store", "policy_version": "retention.dev01", "content_store_allowed": False}
        c = self.coordinator(adapter=adapter, retention=retention)
        status, reply = c.submit(REQUEST, self.trusted, 0)
        self.assertEqual((status, reply["pending_result_policy"]), (202, "metadata_only_no_store"))
        sid = reply["handle"]["submission_id"]
        for _ in range(100):
            if c.status(sid, self.trusted)["submission_state"] == "completed":
                break
            time.sleep(0.01)
        snapshot = c.status(sid, self.trusted)
        self.assertEqual(snapshot["candidate_access"], "not_retained")
        self.assertEqual(snapshot["result_unavailable_reason"], "wait_expired_no_store")
        self.assertNotIn("candidate", snapshot)
        self.assertEqual(len(adapter.sent), 1)
        stored = self.store.db.execute("SELECT record FROM submissions WHERE submission_id=?", (sid,)).fetchone()[0]
        self.assertNotIn("Hello.", stored)
        wait_future_release(c, sid)

    def test_remote_failure_and_unknown_loss(self):
        for adapter, expected in [(FakeAdapter(status=502), "failed_after_transmit"),
                                  (FakeAdapter(unknown=True), "outcome_unknown")]:
            with self.subTest(expected=expected):
                store = SQLiteStore(Path(self.tmp.name) / (expected + ".sqlite"))
                self.addCleanup(store.close)
                c = self.coordinator(store=store, adapter=adapter)
                status, reply = c.submit(REQUEST, self.trusted)
                sid = reply["handle"]["submission_id"]
                self.assertEqual(c.status(sid, self.trusted)["submission_state"], expected)
                self.assertEqual(len(adapter.sent), 1)
                if expected == "failed_after_transmit":
                    self.assertEqual((status, reply["error"]["code"]), (502, "REMOTE_EXECUTION_FAILED"))
                else:
                    self.assertEqual(status, 202)

    def test_usage_replacement_not_additive(self):
        c = self.coordinator()
        _, reply = c.submit(REQUEST, self.trusted)
        sid, aid = reply["handle"]["submission_id"], reply["candidate"]["attempt_id"]
        next_usage = usage_revision(aid, {"input_tokens": 4, "output_tokens": 2})
        self.store.update(sid, {"updated_at": "2030-01-01T00:00:00Z"}, usage=next_usage)
        view = c.status(sid, self.trusted)["attempts"][0]["usage"]
        self.assertEqual(view["revision"]["revision"], 2)
        self.assertEqual(view["revision"]["previous_revision"], 1)
        self.assertEqual(view["revision"]["normalized_usage"]["input_uncached"]["count"], 4)
        self.assertEqual(view["revision"]["cost"]["status"], "unknown")
        self.assertEqual(c.status(sid, self.trusted)["candidate"]["usage"], view)

    def test_retained_content_expires_on_read(self):
        c = self.coordinator()
        _, reply = c.submit(REQUEST, self.trusted)
        sid = reply["handle"]["submission_id"]
        self.store.update(sid, {"content_expires_at": "2020-01-01T00:00:00Z"})
        snapshot = c.status(sid, self.trusted)
        self.assertEqual(snapshot["candidate_access"], "expired")
        self.assertNotIn("candidate", snapshot)
        self.assertIsNone(self.store.get(sid)["candidate"])

    def test_deterministic_adapter_and_control_drift_never_send(self):
        class WrongBody(FakeAdapter):
            def prepare(self, body):
                body = {**body, "model": "model.unauthorized"}
                return super().prepare(body)
        class WrongControl(FakeAdapter):
            def describe(self, prepared, timeout_ms, destination):
                return {**super().describe(prepared, timeout_ms, destination), "method": "GET"}
        for name, adapter in [("body", WrongBody()), ("control", WrongControl())]:
            with self.subTest(name=name):
                store = SQLiteStore(Path(self.tmp.name) / (name + ".sqlite"))
                self.addCleanup(store.close)
                c = self.coordinator(store=store, adapter=adapter)
                code, reply = c.submit(REQUEST, self.trusted)
                self.assertEqual((code, reply["error"]["code"], adapter.sent), (409, "FDC_REJECTED", []))
                self.assertEqual(store.intent_count(reply["handle"]["submission_id"]), 0)

    def test_queued_identity_and_current_facts_block_dispatch(self):
        for name in ("identity", "destination", "classification", "retention"):
            with self.subTest(name=name):
                store = SQLiteStore(Path(self.tmp.name) / ("queued-" + name + ".sqlite"))
                self.addCleanup(store.close)
                adapter = FakeAdapter()
                c = self.coordinator(store=store, adapter=adapter)
                gate = threading.Event()
                blockers = [c.pool.submit(gate.wait, 2) for _ in range(4)]
                try:
                    code, reply = c.submit(REQUEST, self.trusted, 0)
                    self.assertEqual(code, 202)
                    sid = reply["handle"]["submission_id"]
                    self.assertEqual(store.intent_count(sid), 1)
                    if name == "identity": c.identity.pop("token.synthetic")
                    if name == "destination": c.config["model"] = "model.other"
                    if name == "classification": c.classification["sensitivity"] = "restricted"
                    if name == "retention": c.retention["content_store_allowed"] = False
                finally:
                    gate.set()
                    for blocker in blockers: blocker.result(timeout=3)
                for _ in range(100):
                    if store.get(sid)["submission_state"] == "failed_before_transmit": break
                    time.sleep(0.01)
                self.assertEqual(store.get(sid)["submission_state"], "failed_before_transmit")
                self.assertEqual(adapter.sent, [])

    def test_queued_in_place_scope_changes_and_renewal(self):
        for field in ("context_id", "issuer_id", "principal_id", "charging_owner_id",
                      "source_authority_id", "task_id", "prompt_id", "prompt_version", "expires_at"):
            with self.subTest(field=field):
                store = SQLiteStore(Path(self.tmp.name) / ("scope-" + field + ".sqlite"))
                self.addCleanup(store.close)
                adapter = FakeAdapter()
                c = self.coordinator(store=store, adapter=adapter)
                trusted = copy.deepcopy(self.trusted)
                c.identity["token.synthetic"] = trusted
                gate = threading.Event()
                blockers = [c.pool.submit(gate.wait, 3) for _ in range(4)]
                try:
                    code, reply = c.submit(REQUEST, trusted, 0, "token.synthetic")
                    self.assertEqual(code, 202)
                    sid = reply["handle"]["submission_id"]
                    trusted[field] = "2099-01-01T00:00:00Z" if field == "expires_at" else "changed.scope"
                finally:
                    gate.set()
                    for blocker in blockers: blocker.result(timeout=3)
                for _ in range(100):
                    if store.get(sid)["submission_state"] in ("completed", "failed_before_transmit"): break
                    time.sleep(0.01)
                self.assertEqual(store.get(sid)["submission_state"],
                                 "completed" if field == "expires_at" else "failed_before_transmit")
                self.assertEqual(len(adapter.sent), 1 if field == "expires_at" else 0)

    def test_queued_replacement_scope_changes_and_renewal(self):
        for changed in (False, True):
            with self.subTest(changed=changed):
                store = SQLiteStore(Path(self.tmp.name) / f"replacement-{changed}.sqlite")
                self.addCleanup(store.close)
                adapter = FakeAdapter()
                c = self.coordinator(store=store, adapter=adapter)
                admitted = copy.deepcopy(self.trusted)
                c.identity["token.synthetic"] = admitted
                gate = threading.Event()
                blockers = [c.pool.submit(gate.wait, 3) for _ in range(4)]
                try:
                    _, reply = c.submit(REQUEST, admitted, 0, "token.synthetic")
                    sid = reply["handle"]["submission_id"]
                    replacement = copy.deepcopy(admitted)
                    replacement["expires_at"] = "2099-01-01T00:00:00Z"
                    if changed: replacement["source_authority_id"] = "source.replaced"
                    c.identity["token.synthetic"] = replacement
                finally:
                    gate.set()
                    for blocker in blockers: blocker.result(timeout=3)
                for _ in range(100):
                    if store.get(sid)["submission_state"] in ("completed", "failed_before_transmit"): break
                    time.sleep(0.01)
                self.assertEqual(store.get(sid)["submission_state"],
                                 "failed_before_transmit" if changed else "completed")
                self.assertEqual(len(adapter.sent), 0 if changed else 1)

    def test_in_flight_destination_is_attempt_snapshot(self):
        adapter = HeldAdapter()
        c = self.coordinator(adapter=adapter)
        code, reply = c.submit(REQUEST, self.trusted, 0)
        self.assertEqual(code, 202)
        self.assertTrue(adapter.entered.wait(3))
        c.config["model"] = "model.changed_after_dispatch"
        adapter.release.set()
        sid = reply["handle"]["submission_id"]
        for _ in range(100):
            if self.store.get(sid)["submission_state"] == "completed": break
            time.sleep(0.01)
        snapshot = c.status(sid, self.trusted)
        self.assertEqual(snapshot["candidate"]["served_destination"]["model"], "model.demo")
        self.assertEqual(json.loads(adapter.sent[0])["model"], "model.demo")
        intent = json.loads(self.store.db.execute("SELECT intent FROM intents WHERE submission_id=?", (sid,)).fetchone()[0])
        self.assertEqual(intent["destination"]["model"], "model.demo")

    def test_admitted_no_store_cannot_be_relaxed_in_flight(self):
        adapter = HeldAdapter()
        retention = {"retention_class": "no_store", "policy_version": "retention.dev01",
                     "content_store_allowed": False}
        c = self.coordinator(adapter=adapter, retention=retention)
        code, reply = c.submit(REQUEST, self.trusted, 0)
        self.assertEqual((code, reply["pending_result_policy"]), (202, "metadata_only_no_store"))
        self.assertTrue(adapter.entered.wait(3))
        c.retention["content_store_allowed"] = True
        adapter.release.set()
        sid = reply["handle"]["submission_id"]
        for _ in range(100):
            if self.store.get(sid)["submission_state"] == "completed": break
            time.sleep(0.01)
        snapshot = c.status(sid, self.trusted)
        self.assertEqual(snapshot["candidate_access"], "not_retained")
        self.assertEqual(snapshot["result_unavailable_reason"], "wait_expired_no_store")
        self.assertNotIn("Hello.", self.store.db.execute("SELECT record FROM submissions WHERE submission_id=?", (sid,)).fetchone()[0])

    def test_wait_expiry_completion_both_commit_orders(self):
        retention = {"retention_class": "no_store", "policy_version": "retention.dev01",
                     "content_store_allowed": False}
        for finish_first in (False, True):
            with self.subTest(finish_first=finish_first):
                inner = SQLiteStore(Path(self.tmp.name) / f"race-{finish_first}.sqlite")
                self.addCleanup(inner.close)
                adapter = HeldAdapter()
                finished = threading.Event()
                class OrderedStore:
                    def __getattr__(self, name): return getattr(inner, name)
                    def complete_candidate(self, *args):
                        result = inner.complete_candidate(*args)
                        finished.set()
                        return result
                    def mark_wait_expired_no_store(self, sid, at):
                        if finish_first:
                            adapter.release.set()
                            if not finished.wait(3): raise AssertionError("completion did not commit")
                            return inner.mark_wait_expired_no_store(sid, at)
                        result = inner.mark_wait_expired_no_store(sid, at)
                        adapter.release.set()
                        return result
                c = self.coordinator(store=OrderedStore(), adapter=adapter, retention=retention)
                code, reply = c.submit(REQUEST, self.trusted, 0)
                self.assertEqual(code, 202)
                sid = reply["handle"]["submission_id"]
                self.assertTrue(finished.wait(3))
                snapshot = c.status(sid, self.trusted)
                self.assertEqual(snapshot["candidate_access"], "not_retained")
                self.assertEqual(snapshot["result_unavailable_reason"], "wait_expired_no_store")
                self.assertNotIn("candidate", snapshot)

    def test_provider_data_does_not_use_work_serializer(self):
        for name, body, expected in [
            ("decimal_extra", {"text": "Hello.", "usage": {"input_tokens": 3, "fee": 0.5}}, "completed"),
            ("surrogate", {"text": "\ud800", "usage": {}}, "failed_after_transmit"),
            ("malformed_usage", {"text": "Hello.", "usage": "bad"}, "failed_after_transmit"),
            ("unusable", {}, "failed_after_transmit"),
        ]:
            with self.subTest(name=name):
                store = SQLiteStore(Path(self.tmp.name) / (name + ".sqlite"))
                self.addCleanup(store.close)
                adapter = FakeAdapter(body=body)
                c = self.coordinator(store=store, adapter=adapter)
                code, reply = c.submit(REQUEST, self.trusted)
                sid = reply["handle"]["submission_id"]
                self.assertEqual(store.get(sid)["submission_state"], expected)
                self.assertEqual(len(adapter.sent), 1)
                if name == "decimal_extra":
                    self.assertEqual((code, reply["candidate"]["usage"]["revision"]["normalized_usage"]["input_uncached"]["count"]), (200, 3))
                else:
                    self.assertEqual((code, reply["error"]["code"]), (502, "CANDIDATE_UNUSABLE"))

    def test_current_retention_redacts_authorized_status(self):
        c = self.coordinator()
        _, reply = c.submit(REQUEST, self.trusted)
        sid = reply["handle"]["submission_id"]
        c.retention["content_store_allowed"] = False
        snapshot = c.status(sid, self.trusted)
        self.assertEqual(snapshot["candidate_access"], "not_retained")
        self.assertNotIn("candidate", snapshot)
        self.assertIsNone(self.store.get(sid)["candidate"])

    def test_present_optional_fields_validate_before_dispatch(self):
        for key, value in [("parent_call", {}), ("construction_manifest_ref", ""),
                           ("session_id", ""), ("observed_at", "not-a-timestamp"),
                           ("trace_context", {"trace": 1}), ("requested_features", ["text", "not_a_feature"])]:
            with self.subTest(key=key):
                request = copy.deepcopy(REQUEST); request[key] = value
                with self.assertRaises(ContractError) as raised:
                    validate_text_request(request, self.trusted, FIXTURE["destination"],
                                          FIXTURE["prompt_blocks"], FIXTURE["allowed_lineages"])
                self.assertEqual(raised.exception.code, "SCHEMA_INVALID")
        request = copy.deepcopy(REQUEST); request["parent_call"] = "call.demo"
        with self.assertRaises(ContractError) as raised:
            validate_text_request(request, self.trusted, FIXTURE["destination"],
                                  FIXTURE["prompt_blocks"], FIXTURE["allowed_lineages"])
        self.assertEqual(raised.exception.code, "CAPABILITY_UNSUPPORTED")

    def test_no_store_live_delivery_releases_future(self):
        retention = {"retention_class": "no_store", "policy_version": "retention.dev01",
                     "content_store_allowed": False}
        c = self.coordinator(retention=retention)
        code, reply = c.submit(REQUEST, self.trusted, 1000)
        self.assertEqual((code, reply["state"], reply["candidate"]["output_blocks"][0]["text"]),
                         (200, "delivered", "Hello."))
        sid = reply["handle"]["submission_id"]
        wait_future_release(c, sid)
        snapshot = c.status(sid, self.trusted)
        self.assertEqual(snapshot["candidate_access"], "not_retained")
        self.assertNotIn("candidate", snapshot)
        stored = self.store.db.execute("SELECT record FROM submissions WHERE submission_id=?", (sid,)).fetchone()[0]
        self.assertNotIn("Hello.", stored)

    def test_post_response_store_failure_is_not_false_provider_failure(self):
        class FailFinal:
            def __init__(self, inner): self.inner = inner
            def __getattr__(self, name): return getattr(self.inner, name)
            def complete_candidate(self, *_args): raise OSError("synthetic final commit failure")
        c = self.coordinator(store=FailFinal(self.store))
        code, reply = c.submit(REQUEST, self.trusted)
        self.assertEqual((code, reply["state"]), (202, "pending"))
        record = self.store.by_work({"principal_id": self.trusted["principal_id"],
            **{k: REQUEST[k] for k in ("task_id", "step_id", "step_revision", "execution_generation")}})
        self.assertEqual((record["submission_state"], record["dispatch_state"], len(self.adapter.sent)),
                         ("outcome_unknown", "outcome_unknown", 1))
        self.assertNotIn("terminal_failure", record)
        self.assertEqual(record["usage"]["state"], "available")

if __name__ == "__main__":
    unittest.main()
