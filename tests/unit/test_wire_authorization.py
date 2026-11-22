"""Independent bearer policy against actual work and accounting handlers."""

import ast
from copy import deepcopy
from email.message import Message
import hashlib
from http.client import HTTPResponse
import io
import json
import unittest
from unittest.mock import patch

from ezllmrouter_server.wire_http.handler import WireHandler
from ezllmrouter_server.wire_http.integration import READ_ROUTES
from ezllmrouter_server.wire_http.transport import WireTransport
from tests.operator_console.test_authorization_matrix_sockets import ResponseSocket
from tests.wire_authorization_fixtures import ACTORS, FIXTURE_KEY, RESULT_CANARY, WireFixture
from tests.wire_authorization_policy import POLICY, ROOT, expected, routes


class WireAuthorizationTests(WireFixture, unittest.TestCase):
    def exchange(
        self,
        row,
        actor="work_owner",
        *,
        auth=None,
        version_headers=None,
        body=None,
        path=None,
        method=None,
    ):
        request_path, request_body = self.request_for(row, actor)
        method, path = method or row["method"], path or request_path
        raw = (
            json.dumps(request_body if body is None else body, separators=(",", ":")).encode()
            if method == "POST"
            else b""
        )
        headers = self.headers_for(row, actor, auth, version_headers)
        handler = WireHandler.__new__(WireHandler)
        handler.application = self.wire.handler.keywords["application"]
        handler.server, handler.path, handler.command = self.wire, path, method
        handler.request_version, handler.requestline = "HTTP/1.1", method + " " + path + " HTTP/1.1"
        handler.client_address, handler.close_connection = ("127.0.0.1", 12345), False
        handler.headers = Message()
        for key, value in headers:
            handler.headers[key] = value
        if method == "POST":
            handler.headers["Content-Type"] = "application/json"
            handler.headers["Content-Length"] = str(len(raw))
        handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
        getattr(handler, "do_" + method)()
        response = HTTPResponse(ResponseSocket(handler.wfile.getvalue()), method=method)
        response.begin()
        return response.status, response.headers, response.read()

    def headers_for(self, row, actor, auth, version_headers):
        name = (
            "EzLLMRouter-Contract-Version"
            if row["family"] == "work"
            else "EzLLMRouter-Integration-Version"
        )
        headers = [("Host", "127.0.0.1:48760"), ("Connection", "close")]
        headers += [
            (name, value)
            for value in ([row["version"]] if version_headers is None else version_headers)
        ]
        headers += [
            ("Authorization", value)
            for value in (["Bearer " + self.tokens[actor]] if auth is None else auth)
        ]
        return headers

    def assert_response(self, row, status, headers, raw, wanted):
        self.assertEqual(status, wanted, (row["version"], row["method"], row["case"], raw[:300]))
        name = (
            "EzLLMRouter-Contract-Version"
            if row["family"] == "work"
            else "EzLLMRouter-Integration-Version"
        )
        self.assertEqual(headers[name], row["version"])
        if row["family"] == "integration":
            self.assertEqual(headers["Cache-Control"], "no-store, max-age=0")
        if status >= 400:
            self.assertNotIn(RESULT_CANARY.encode(), raw)
            self.assertNotIn(FIXTURE_KEY.encode(), raw)
            value = json.loads(raw)
            self.assertNotIn("candidate", value)
            self.assertNotIn("items", value)
            code = value.get("code", value.get("error", {}).get("code"))
            if status == 401:
                self.assertEqual(
                    code, "POLICY_DENIED" if row["version"] == "0.3" else "AUTHENTICATION_FAILED"
                )

    def test_policy_covers_reviewed_route_sources_and_every_version_binding(self):
        bound = list(routes())
        identities = [(r["family"], r["version"], r["method"], r["path"]) for r in bound]
        self.assertEqual(len(identities), 42)
        self.assertEqual(len(set(identities)), 42)
        self.assertEqual(len(POLICY["source_sha256"]), 3)
        for name, expected_hash in POLICY["source_sha256"].items():
            self.assertEqual(
                hashlib.sha256((ROOT / name).read_bytes()).hexdigest(),
                expected_hash,
                "review changed wire routing/authentication: " + name,
            )
        tree = ast.parse((ROOT / "server/src/ezllmrouter_server/wire_http/handler.py").read_text())
        for method in ("do_GET", "do_POST"):
            function = next(
                n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == method
            )
            literals = {
                n.value
                for n in ast.walk(function)
                if isinstance(n, ast.Constant)
                and isinstance(n.value, str)
                and n.value.startswith("/v1/")
            }
            self.assertEqual(literals, set(POLICY["work_literals"][method]))
        reads = {
            (version, pattern) for versions, pattern, _action in READ_ROUTES for version in versions
        }
        expected_reads = set()
        for row in bound:
            if row["family"] == "integration" and row["method"] == "GET":
                suffix = row["path"].replace("/integration/v{version}", "")
                for field in ("account", "event", "snapshot", "credential_account"):
                    suffix = suffix.replace("{" + field + "}", "[^/]+")
                expected_reads.add((row["version"], suffix))
        self.assertEqual(reads, expected_reads)

    def test_every_route_rejects_missing_invalid_duplicate_revoked_and_suspended_bearers(self):
        bad = (
            [],
            ["Basic irrelevant"],
            ["Bearer invalid"],
            ["Bearer " + self.tokens["revoked"]],
            ["Bearer " + self.tokens["suspended"]],
            ["Bearer " + self.tokens["work_owner"]] * 2,
        )
        original = WireTransport._json_bytes
        with patch.object(
            WireTransport, "_json_bytes", autospec=True, side_effect=original
        ) as reader:
            for row in routes():
                for auth_case, authorization in enumerate(bad):
                    with self.subTest(
                        version=row["version"], route=row["case"], auth_case=auth_case
                    ):
                        before = self.footprint()
                        count = reader.call_count
                        self.assert_response(row, *self.exchange(row, auth=authorization), 401)
                        self.assertEqual(
                            reader.call_count, count, "unauthenticated body was parsed"
                        )
                        self.assertEqual(
                            self.footprint(), before, "denial changed data or dispatched work"
                        )

    def test_every_route_requires_one_matching_protocol_version_before_body_dispatch(self):
        for row in routes():
            for versions in ([], [row["version"], row["version"]], ["99"]):
                with self.subTest(version=row["version"], route=row["case"], headers=versions):
                    before = self.footprint()
                    status, _headers, raw = self.exchange(row, version_headers=versions)
                    self.assertEqual(status, 426, raw)
                    self.assertEqual(self.footprint(), before)

    def test_active_identities_obey_independent_permissions_with_valid_bodies(self):
        for row in routes():
            for actor in ACTORS:
                with self.subTest(version=row["version"], route=row["case"], actor=actor):
                    before = self.footprint()
                    wanted = expected(row, actor)
                    self.assert_response(row, *self.exchange(row, actor), wanted)
                    if wanted >= 400:
                        self.assertEqual(
                            self.footprint(), before, "denied request changed data or sent work"
                        )

    def test_wrong_methods_cannot_reach_a_valid_operation(self):
        for row in routes():
            with self.subTest(version=row["version"], route=row["case"]):
                before = self.footprint()
                method = "POST" if row["method"] == "GET" else "GET"
                path = self.request_for(row)[0].split("?", 1)[0]
                status, _headers, raw = self.exchange(row, method=method, path=path, body={})
                self.assertEqual(status, 404, raw)
                self.assertEqual(self.footprint(), before)

    def test_integration_only_mode_hides_every_controlled_work_route(self):
        self.mode(True)
        for row in routes():
            with self.subTest(version=row["version"], route=row["case"]):
                if row["family"] == "work":
                    before = self.footprint()
                    status, _headers, raw = self.exchange(row)
                    self.assertEqual(status, 404, raw)
                    self.assertEqual(self.footprint(), before)
                else:
                    actor = next(iter(POLICY["permissions"][row["permission"]]))
                    self.assert_response(row, *self.exchange(row, actor), expected(row, actor))

    def test_profile_03_cannot_fall_back_to_legacy_attribution_routes(self):
        for row in routes():
            if row["family"] != "work" or row["case"] not in {
                "run_read",
                "run_create",
                "outcome_read",
                "outcome_create",
            }:
                continue
            actor = "evaluator" if row["case"].startswith("outcome") else "work_owner"
            row = {**row, "version": "0.3"}
            before = self.footprint()
            self.assert_response(row, *self.exchange(row, actor), 404)
            self.assertEqual(self.footprint(), before)

    def test_work_scope_checks_task_and_principal_without_an_administrator_bypass(self):
        token = self.tokens["work_owner"]
        trusted = self.coordinator.authenticate(token)
        self.coordinator.identity[token] = {**trusted, "task_id": "task.wire.other"}
        for row in routes():
            if row["family"] == "work" and row["case"] in {"status", "by_work"}:
                with self.subTest(version=row["version"], route=row["case"]):
                    before = self.footprint()
                    self.assert_response(row, *self.exchange(row), 404)
                    self.assertEqual(self.footprint(), before)

    def test_expired_work_context_and_expired_operator_credentials_are_rejected(self):
        token = self.tokens["work_owner"]
        self.coordinator.identity[token] = {
            **self.coordinator.authenticate(token),
            "expires_at": "2000-01-01T00:00:00Z",
        }
        for row in routes():
            if row["family"] == "work":
                self.assert_response(row, *self.exchange(row), 401)
        expired = self.registry.issue_local_operator_token("owner.local")
        verifier = hashlib.sha256(expired.encode()).hexdigest()
        self.registry._operator_tokens[verifier] = ("owner.local", 0)
        for row in routes():
            self.assert_response(row, *self.exchange(row, auth=["Bearer " + expired]), 401)

    def test_fresh_work_is_admitted_once_and_replayed_without_another_dispatch(self):
        for row in routes():
            if row["family"] != "work" or row["case"] != "submit":
                continue
            with self.subTest(version=row["version"]):
                body = deepcopy(self.requests[row["version"]])
                if row["version"] == "0.2":
                    body["step_id"] = "step.wire.fresh.02"
                else:
                    body["work_selector"]["step_id"] = "step.wire.fresh.03"
                counts = len(self.adapter.sent), self.executor.calls
                status, headers, raw = self.exchange(row, body=body)
                self.assert_response(row, status, headers, raw, 200)
                handle = json.loads(raw)["handle"]
                self.assertEqual(handle["work_key"]["principal_id"], "svc.demo")
                wanted = (
                    (counts[0] + 1, counts[1])
                    if row["version"] == "0.2"
                    else (counts[0], counts[1] + 1)
                )
                self.assertEqual((len(self.adapter.sent), self.executor.calls), wanted)
                replay = self.exchange(row, body=body)
                self.assert_response(row, *replay, expected(row, "work_owner"))
                self.assertEqual(json.loads(replay[2])["handle"], handle)
                self.assertEqual((len(self.adapter.sent), self.executor.calls), wanted)

    def test_fresh_accounting_writes_have_positive_controls_and_preserve_exact_ids(self):
        for version in ("1", "2", "3"):
            data = self.data[version]
            for case, actor in (
                ("dataset_create", "owner"),
                ("account_create", "owner"),
                ("event_create", "ingest"),
                ("snapshot_create", "ingest"),
            ):
                if case == "snapshot_create" and version == "1":
                    continue
                row = next(
                    r
                    for r in routes()
                    if r["family"] == "integration"
                    and r["version"] == version
                    and r["case"] == case
                )
                with self.subTest(version=version, operation=case):
                    path, body = self.request_for(row, actor)
                    field = {
                        "dataset_create": "dataset_id",
                        "account_create": "account_id",
                        "event_create": "event_id",
                        "snapshot_create": "snapshot_id",
                    }[case]
                    body[field] += ".fresh"
                    if case == "event_create" and version != "1":
                        body.update(
                            attempt_id=body["attempt_id"] + ".fresh",
                            context_ref=data["snapshot"]["snapshot_id"] + ".fresh",
                            logical_operation_id=body["logical_operation_id"] + ".fresh",
                        )
                    if case == "snapshot_create":
                        body["attempt_id"] += ".fresh"
                    before = self.store.db.total_changes
                    status, headers, raw = self.exchange(row, actor, path=path, body=body)
                    self.assert_response(row, status, headers, raw, 201)
                    self.assertIn(body[field].encode(), raw)
                    self.assertGreater(self.store.db.total_changes, before)
        self.assertEqual((len(self.adapter.sent), self.executor.calls), (1, 1))

    def test_a_console_role_needs_an_explicit_execution_grant(self):
        row = next(
            r
            for r in routes()
            if r["family"] == "work" and r["case"] == "submit" and r["version"] == "0.2"
        )
        body = deepcopy(self.requests["0.2"])
        body["step_id"] = "step.wire.role-grant"
        before = self.footprint()
        self.assert_response(row, *self.exchange(row, "reader", body=body), 403)
        self.assertEqual(self.footprint(), before)
        self.change(
            "set_grant",
            self.principals["reader"],
            0,
            {
                "configuration_ref": "cfg.demo",
                "status": "active",
                "purposes": ["execution"],
                "task_classes": ["class.demo"],
            },
        )
        self.assert_response(row, *self.exchange(row, "reader", body=body), 200)
        self.assertEqual(len(self.adapter.sent), 2)
        before = self.footprint()
        self.assert_response(row, *self.exchange(row, "other", body=body), 403)
        self.assertEqual(self.footprint(), before)

    def test_current_historical_read_grants_are_rechecked_for_profile_03(self):
        service = self.coordinator.successor
        identity = service.contexts[self.tokens["work_owner"]]["identity"]
        service.authority.set_historical_access(
            identity, read=False, write=True, resume=True, observed_at="2026-11-21T12:00:00Z"
        )
        for row in routes():
            if (
                row["family"] == "work"
                and row["version"] == "0.3"
                and row["case"] in {"status", "by_work"}
            ):
                before = self.footprint()
                self.assert_response(row, *self.exchange(row), 404)
                self.assertEqual(self.footprint(), before)

    def test_work_identity_cannot_be_reused_across_profiles(self):
        row = next(
            r
            for r in routes()
            if r["family"] == "work" and r["version"] == "0.3" and r["case"] == "submit"
        )
        body = deepcopy(self.requests["0.3"])
        body["work_selector"]["step_id"] = self.requests["0.2"]["step_id"]
        before = self.footprint()
        status, headers, raw = self.exchange(row, body=body)
        self.assert_response(row, status, headers, raw, 409)
        self.assertEqual(json.loads(raw)["code"], "WORK_VERSION_CONFLICT")
        self.assertEqual(self.footprint(), before)

    def test_account_receipt_snapshot_and_secret_lookups_cannot_cross_dataset_bindings(self):
        for case, version, foreign_field, foreign_value, actor in (
            (
                "eligibility",
                "2",
                self.data["2"]["account"]["account_id"],
                self.data["1"]["account"]["account_id"],
                "ingest",
            ),
            (
                "receipt",
                "2",
                self.data["2"]["event"]["event_id"],
                self.data["1"]["event"]["event_id"],
                "ingest",
            ),
            ("snapshot_read", "3", "snapshot.wire.v3", "snapshot.wire.v2", "ingest"),
            ("resolve", "3", "dataset.wire.v3", "dataset.wire.v2", "consumer"),
        ):
            with self.subTest(resource=case):
                row = next(
                    r
                    for r in routes()
                    if r["family"] == "integration"
                    and r["version"] == version
                    and r["case"] == case
                )
                path = self.request_for(row, actor)[0].replace(foreign_field, foreign_value)
                before = self.footprint()
                self.assert_response(row, *self.exchange(row, actor, path=path), 404)
                self.assertEqual(self.footprint(), before)
