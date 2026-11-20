"""Encrypted integration credential registration and scoped resolution."""

import json
import http.client
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]

from ezllmrouter_server.integration_credentials import DatabaseCredentialStore
from ezllmrouter_server.integration_accounting import ExternalAccounting, IntegrationError
from ezllmrouter_server.registry import Registry
from ezllmrouter_server.store import SQLiteStore
from ezllmrouter_server.operator_projection import OperatorProjection
from ezllmrouter_server.operator_web import serve as serve_operator
from ezllmrouter_server.web import serve as serve_api


class Authority:
    def __init__(self):
        self.gate = threading.RLock()
        self.epoch = 0


DEST = {
    "configuration_ref": "cfg.demo",
    "service": "litellm.dev04",
    "endpoint": "127.0.0.1",
    "model": "model.demo",
    "model_version": "v1",
    "processing_region": "local",
}
TRUSTED = {"principal_id": "svc.demo", "charging_owner_id": "team.demo"}


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = SQLiteStore(self.root / "service.sqlite")
        self.addCleanup(self.store.close)
        self.registry = Registry(
            self.store,
            Authority(),
            legacy_destination=DEST,
            legacy_token="synthetic-legacy-service-token-000000000000",
            legacy_trusted=TRUSTED,
        )
        for subject in ("svc.integration", "svc.vega.credential-consumer"):
            self.registry.mutate(
                "owner.local",
                {
                    "operation_id": "op.create." + subject,
                    "action": "create_principal",
                    "subject": subject,
                    "expected_revision": 0,
                    "data": {
                        "display_name": subject,
                        "kind": "service",
                        "owner": "owner.local",
                        "role": "ordinary",
                    },
                },
            )
            _, token = self.registry.provision_credential(
                "owner.local", subject, 1, "op.credential." + subject
            )
            self.registry.mutate(
                "owner.local",
                {
                    "operation_id": "op.activate." + subject,
                    "action": "principal_state",
                    "subject": subject,
                    "expected_revision": 2,
                    "data": {"status": "active", "reason": "controlled test"},
                },
            )
            if subject == "svc.vega.credential-consumer":
                self.consumer = self.registry.credential_principal(token)
                self.consumer_token = token
        self.owner = self.registry.principal("owner.local")
        self.dataset = "dataset.synthetic.credential.controlled"
        self.registry.integration.create_dataset(
            self.owner,
            {
                "dataset_id": self.dataset,
                "platform_id": "platform.vega",
                "environment_id": "environment.synthetic.test",
                "owner_id": "owner.local",
                "ingest_principal_id": "svc.integration",
                "activated_at": "2026-11-03T00:00:00Z",
            },
        )
        self.calls = []

        def discover(adapter, settings, key, operation, **kwargs):
            self.calls.append((adapter, settings["origin"], operation))
            if key == "known-invalid-fixture-key":
                return {"state": "failed", "reason": "credential_rejected", "models": []}
            models = (
                ["claude-opus-4-8", "claude-sonnet-4-5-20250929"]
                if adapter.startswith("anthropic")
                else ["grok-4"]
            )
            return {
                "state": "observed",
                "reason": "inventory_not_inference_entitlement",
                "models": models,
                "details": [{"id": model, "name": model} for model in models],
                "has_more": False,
            }

        self.key_path = self.root / "secrets/integration.keys.json"
        self.credentials = DatabaseCredentialStore(
            self.registry, self.key_path, discover=discover, controlled=True
        )
        self.registry.integration_credentials = self.credentials

    def connect(
        self, key="known-fixture-api-key-0001", provider="anthropic", operation="op.connect.1"
    ):
        return self.credentials.connect(
            self.owner,
            {
                "dataset_id": self.dataset,
                "provider": provider,
                "api_key": key,
                "friendly_name": "Local test",
                "operation_id": operation,
            },
        )

    def test_credential_mutations_reject_non_object_bodies_without_discovery(self):
        for name in ("refresh", "replace", "disable", "retire"):
            for body in (None, [], "text", 12):
                with (
                    self.subTest(operation=name, body=body),
                    self.assertRaises(IntegrationError) as rejected,
                ):
                    getattr(self.credentials, name)(self.owner, "account.invalid-body", body)
                self.assertEqual(
                    (rejected.exception.code, rejected.exception.status), ("SCHEMA_INVALID", 400)
                )
        self.assertEqual(self.calls, [])

    def test_connect_save_restart_replace_and_restrict(self):
        pending = self.connect()
        self.assertEqual(pending["state"], "pending")
        self.assertEqual(pending["discovery"]["state"], "observed")
        self.assertEqual(self.connect(), pending)
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn("known-fixture-api-key-0001", json.dumps(pending))
        self.assertNotIn("known-fixture-api-key-0001", "\n".join(self.store.db.iterdump()))
        self.assertEqual(self.key_path.stat().st_mode & 0o077, 0)
        account_id = pending["account_id"]
        saved = self.credentials.save(
            self.owner,
            account_id,
            {
                "dataset_id": self.dataset,
                "expected_revision": pending["revision"],
                "selected_models": ["claude-opus-4-8"],
                "allowed_operations": [],
            },
        )
        self.assertEqual(saved["state"], "connected")
        secret = self.credentials.resolve_for(
            self.consumer,
            self.dataset,
            account_id,
            "claude-opus-4-8",
            "generation",
            "vega-provider-dispatch",
        )
        self.assertEqual(secret["api_key"], "known-fixture-api-key-0001")
        self.assertEqual(secret["credential_version"], 1)
        original_discover = self.credentials.discover
        self.credentials.discover = lambda *_args, **_kwargs: {
            "state": "observed",
            "reason": "inventory_not_inference_entitlement",
            "models": ["claude-sonnet-4-5-20250929", "claude-new-unselected"],
            "details": [],
            "has_more": False,
        }
        refreshed = self.credentials.refresh(
            self.owner,
            account_id,
            {"dataset_id": self.dataset, "expected_revision": saved["revision"]},
        )
        self.assertEqual(refreshed["discovery"]["record_revision"], refreshed["revision"])
        self.assertEqual(refreshed["selected_models"], ["claude-opus-4-8"])
        self.assertIn("claude-new-unselected", refreshed["discovery"]["models"])
        self.credentials.discover = original_discover
        saved = refreshed
        with self.assertRaises(IntegrationError):
            self.credentials.resolve_for(
                self.consumer,
                self.dataset,
                account_id,
                "claude-sonnet-4-5-20250929",
                "generation",
                "vega-provider-dispatch",
            )
        with self.assertRaises(IntegrationError):
            self.credentials.resolve_for(
                self.registry.principal("svc.integration"),
                self.dataset,
                account_id,
                "claude-opus-4-8",
                "generation",
                "vega-provider-dispatch",
            )
        reopened = DatabaseCredentialStore(
            self.registry, self.key_path, discover=self.credentials.discover, controlled=True
        )
        self.assertEqual(
            reopened.resolve_for(
                self.consumer,
                self.dataset,
                account_id,
                "claude-opus-4-8",
                "generation",
                "vega-provider-dispatch",
            )["credential_version"],
            1,
        )
        failed = reopened.replace(
            self.owner,
            account_id,
            {
                "dataset_id": self.dataset,
                "expected_revision": saved["revision"],
                "api_key": "known-invalid-fixture-key",
            },
        )
        self.assertEqual(failed["selected_version"], 1)
        self.assertEqual(failed["replacement"]["reason"], "credential_rejected")
        changed = reopened.replace(
            self.owner,
            account_id,
            {
                "dataset_id": self.dataset,
                "expected_revision": saved["revision"],
                "api_key": "known-fixture-api-key-0002",
            },
        )
        self.assertEqual(changed["selected_version"], 2)
        self.assertEqual(
            reopened.resolve_for(
                self.consumer,
                self.dataset,
                account_id,
                "claude-opus-4-8",
                "generation",
                "vega-provider-dispatch",
            )["api_key"],
            "known-fixture-api-key-0002",
        )
        with self.assertRaises(IntegrationError):
            reopened.retire(
                self.owner,
                account_id,
                {
                    "dataset_id": self.dataset,
                    "expected_revision": changed["revision"],
                    "version": 1,
                    "acknowledged_version": 1,
                },
            )
        changed = reopened.retire(
            self.owner,
            account_id,
            {
                "dataset_id": self.dataset,
                "expected_revision": changed["revision"],
                "version": 1,
                "acknowledged_version": 2,
            },
        )
        self.assertIsNone(
            self.store.db.execute(
                "SELECT 1 FROM integration_credential_versions WHERE account_id=? AND version=1",
                (account_id,),
            ).fetchone()
        )
        disabled = reopened.disable(
            self.owner,
            account_id,
            {"dataset_id": self.dataset, "expected_revision": changed["revision"]},
        )
        self.assertEqual(disabled["state"], "disabled")
        with self.assertRaises(IntegrationError):
            reopened.resolve_for(
                self.consumer,
                self.dataset,
                account_id,
                "claude-opus-4-8",
                "generation",
                "vega-provider-dispatch",
            )

    def test_missing_and_wrong_key_fail_without_overwriting(self):
        self.connect()
        saved = self.key_path.read_bytes()
        self.key_path.unlink()
        with self.assertRaisesRegex(RuntimeError, "SECRET_KEYRING_MISSING"):
            DatabaseCredentialStore(
                self.registry, self.key_path, discover=self.credentials.discover
            )
        self.assertFalse(self.key_path.exists())
        self.key_path.write_bytes(b"x" * 32)
        self.key_path.chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, "SECRET_KEYRING_UNAVAILABLE"):
            DatabaseCredentialStore(
                self.registry, self.key_path, discover=self.credentials.discover
            )
        self.assertNotEqual(saved, self.key_path.read_bytes())

    def test_existing_connection_identity_in_fresh_accounting_collection(self):
        pending = self.connect()
        saved = self.credentials.save(
            self.owner,
            pending["account_id"],
            {
                "dataset_id": self.dataset,
                "expected_revision": pending["revision"],
                "selected_models": ["claude-opus-4-8"],
                "allowed_operations": [],
            },
        )
        account_id = saved["account_id"]
        real = "dataset.local.real.controlled-account-scope"
        self.registry.integration.accounting_retention_days = 30  # test-only, no owner adoption
        self.registry.integration.create_dataset(
            self.owner,
            {
                "dataset_id": real,
                "platform_id": "platform.vega",
                "environment_id": "environment.synthetic.test",
                "owner_id": "owner.local",
                "ingest_principal_id": "svc.integration",
                "activated_at": "2026-11-03T00:00:00Z",
            },
        )
        body = {
            "dataset_id": real,
            "account_id": account_id,
            "provider_id": saved["provider_id"],
            "credential_ref": saved["credential_ref"],
            "allowed_models": ["claude-opus-4-8"],
            "allowed_operations": [],
            "state": "usable",
        }
        self.assertEqual(self.registry.integration.create_account(self.owner, body, "3")[0], 201)
        self.assertEqual(self.registry.integration.create_account(self.owner, body, "3")[0], 200)
        self.assertTrue(
            self.registry.integration.eligibility(
                self.owner,
                real,
                account_id,
                "claude-opus-4-8",
                "3",
                "generation",
                "generation",
                "known_model",
            )["usable"]
        )
        self.assertEqual(
            self.credentials.resolve_for(
                self.consumer,
                self.dataset,
                account_id,
                "claude-opus-4-8",
                "generation",
                "vega-provider-dispatch",
            )["api_key"],
            "known-fixture-api-key-0001",
        )
        with self.assertRaises(IntegrationError):
            self.credentials.resolve_for(
                self.consumer,
                real,
                account_id,
                "claude-opus-4-8",
                "generation",
                "vega-provider-dispatch",
            )
        self.registry.integration.set_account_state(
            self.owner,
            account_id,
            {"dataset_id": real, "expected_revision": 1, "state": "disabled"},
            "3",
        )
        self.assertFalse(
            self.registry.integration.eligibility(
                self.owner,
                real,
                account_id,
                "claude-opus-4-8",
                "3",
                "generation",
                "generation",
                "known_model",
            )["usable"]
        )
        source = self.store.db.execute(
            "SELECT record FROM integration_accounts WHERE id=? AND dataset_id=?",
            (account_id, self.dataset),
        ).fetchone()
        self.assertEqual(json.loads(source[0])["state"], "usable")
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM integration_account_history WHERE id=?", (account_id,)
            ).fetchone()[0],
            3,
        )

    def test_initial_schema_reopen_preserves_saved_binding(self):
        pending = self.connect()
        saved = self.credentials.save(
            self.owner,
            pending["account_id"],
            {
                "dataset_id": self.dataset,
                "expected_revision": pending["revision"],
                "selected_models": ["claude-opus-4-8"],
                "allowed_operations": [],
            },
        )
        account_id = saved["account_id"]
        before = self.store.db.execute(
            "SELECT record FROM integration_accounts WHERE id=?", (account_id,)
        ).fetchone()[0]
        self.registry.integration = ExternalAccounting(self.registry)
        from ezllmrouter_server.schema import VERSION

        self.assertEqual(self.store.db.execute("PRAGMA user_version").fetchone()[0], VERSION)
        self.assertEqual(
            self.store.db.execute(
                "SELECT record FROM integration_accounts WHERE id=?", (account_id,)
            ).fetchone()[0],
            before,
        )
        self.assertEqual(
            self.credentials.resolve_for(
                self.consumer,
                self.dataset,
                account_id,
                "claude-opus-4-8",
                "generation",
                "vega-provider-dispatch",
            )["api_key"],
            "known-fixture-api-key-0001",
        )

    def test_failed_discovery_stays_encrypted_pending(self):
        pending = self.connect("known-invalid-fixture-key")
        self.assertEqual(pending["discovery"]["state"], "failed")
        with self.assertRaises(IntegrationError):
            self.credentials.save(
                self.owner,
                pending["account_id"],
                {
                    "dataset_id": self.dataset,
                    "expected_revision": pending["revision"],
                    "selected_models": ["grok-4"],
                    "allowed_operations": [],
                },
            )
        self.assertFalse(
            self.store.db.execute(
                "SELECT 1 FROM integration_accounts WHERE id=?", (pending["account_id"],)
            ).fetchone()
        )
        account_id = pending["account_id"]
        old = self.credentials._binding(account_id)
        old["created_at"] = "2020-01-01T00:00:00Z"
        self.store._transaction(
            lambda: self.store.db.execute(
                "UPDATE integration_credential_bindings SET record=? WHERE account_id=?",
                (json.dumps(old), account_id),
            )
        )
        DatabaseCredentialStore(
            self.registry, self.key_path, discover=self.credentials.discover, controlled=True
        )
        self.assertEqual(self.credentials._binding(account_id)["state"], "pending")
        failed = self.credentials.replace(
            self.owner,
            account_id,
            {
                "dataset_id": self.dataset,
                "expected_revision": pending["revision"],
                "api_key": "known-invalid-fixture-key",
            },
        )
        self.assertEqual((failed["account_id"], failed["state"]), (account_id, "pending"))
        self.assertEqual(failed["revision"], pending["revision"] + 1)
        with self.assertRaises(IntegrationError):
            self.credentials.replace(
                self.owner,
                account_id,
                {
                    "dataset_id": self.dataset,
                    "expected_revision": pending["revision"],
                    "api_key": "known-fixture-api-key-0002",
                },
            )
        accepted = self.credentials.replace(
            self.owner,
            account_id,
            {
                "dataset_id": self.dataset,
                "expected_revision": failed["revision"],
                "api_key": "known-fixture-api-key-0002",
            },
        )
        self.assertEqual((accepted["account_id"], accepted["state"]), (account_id, "pending"))
        self.assertEqual(accepted["discovery"]["state"], "observed")
        self.assertEqual(accepted["discovery"]["credential_version"], accepted["pending_version"])
        self.assertEqual(accepted["discovery"]["record_revision"], accepted["revision"])
        saved = self.credentials.save(
            self.owner,
            account_id,
            {
                "dataset_id": self.dataset,
                "expected_revision": accepted["revision"],
                "selected_models": ["claude-opus-4-8"],
                "allowed_operations": [],
            },
        )
        self.assertEqual((saved["account_id"], saved["state"]), (account_id, "connected"))
        self.assertEqual(len(self.credentials.list(self.owner, self.dataset)["items"]), 1)
        reopened = DatabaseCredentialStore(
            self.registry, self.key_path, discover=self.credentials.discover, controlled=True
        )
        self.assertEqual(
            reopened.resolve_for(
                self.consumer,
                self.dataset,
                account_id,
                "claude-opus-4-8",
                "generation",
                "vega-provider-dispatch",
            )["api_key"],
            "known-fixture-api-key-0002",
        )


class CredentialHTTPTests(unittest.TestCase):
    setUp = CredentialTests.setUp
    connect = CredentialTests.connect

    def test_owner_http_journey_and_nonowner_boundary(self):
        fixture = json.loads((ROOT / "tools/gateway/evidence/dev05_fixture.json").read_text())
        operator_port = 0
        origin = f"http://127.0.0.1:{operator_port}"

        class NoRunner:
            def run(self, *_):
                raise AssertionError("provider inference forbidden")

        server = serve_operator(
            "127.0.0.1",
            operator_port,
            projection=OperatorProjection(self.store, "svc.demo"),
            runner=NoRunner(),
            password="p" * 40,
            fixture=fixture,
            build={"commit": "controlled"},
            web_root=ROOT / "web",
            worker_probe=lambda: {"state": "ok"},
            sender_status=lambda: {"state": "ok"},
            registry=self.registry,
            integration_only=True,
        )
        operator_port = server.server_port
        origin = f"http://127.0.0.1:{operator_port}"
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        self.addCleanup(
            lambda: (
                server.shutdown(),
                server.server_close(),
                thread.join(timeout=3),
                server.operator_jobs.shutdown(wait=True),
            )
        )

        def operator(method, path, body=None, cookie=None, csrf=None):
            conn = http.client.HTTPConnection("127.0.0.1", operator_port, timeout=3)
            headers = {"Host": f"127.0.0.1:{operator_port}"}
            if method == "POST":
                headers["Origin"] = origin
            if cookie:
                headers["Cookie"] = cookie
            if csrf:
                headers["X-EzLLMRouter-CSRF"] = csrf
            if body is not None:
                headers["Content-Type"] = "application/json"
            try:
                conn.request(method, path, json.dumps(body) if body is not None else None, headers)
                response = conn.getresponse()
                return response.status, dict(response.getheaders()), json.loads(response.read())
            finally:
                conn.close()

        status, headers, login = operator("POST", "/operator/v1/login", {"password": "p" * 40})
        self.assertEqual(operator("GET", "/operator/v1/session")[0], 401)
        self.assertEqual(status, 200)
        cookie, csrf = headers["Set-Cookie"].split(";", 1)[0], login["csrf"]
        body = {
            "dataset_id": self.dataset,
            "provider": "anthropic",
            "api_key": "known-fixture-api-key-0001",
            "friendly_name": "Owner test",
            "operation_id": "op.owner.connect",
        }
        self.assertEqual(
            operator("POST", "/operator/v1/integration/connections", body, cookie)[0], 403
        )
        status, _, pending = operator(
            "POST", "/operator/v1/integration/connections", body, cookie, csrf
        )
        self.assertEqual(status, 201)
        self.assertNotIn("api_key", pending)
        listing = "/operator/v1/integration/connections?dataset_id=" + self.dataset
        session_status, _, restored = operator("GET", "/operator/v1/session", cookie=cookie)
        self.assertEqual(session_status, 200)
        self.assertEqual(restored["csrf"], csrf)
        self.assertEqual(restored["principal_id"], "owner.local")
        self.assertEqual(operator("GET", "/operator/v1/integration/identity")[0], 401)
        identity_status, _, identity = operator(
            "GET", "/operator/v1/integration/identity", cookie=cookie
        )
        self.assertEqual((identity_status, identity), (200, {"user": None}))
        self.assertEqual(
            operator("GET", listing, cookie=cookie)[2]["items"][0]["account_id"],
            pending["account_id"],
        )
        save = {
            "dataset_id": self.dataset,
            "expected_revision": pending["revision"],
            "selected_models": ["claude-opus-4-8"],
            "allowed_operations": [],
        }
        status, _, saved = operator(
            "POST",
            "/operator/v1/integration/connections/" + pending["account_id"] + "/save",
            save,
            cookie,
            csrf,
        )
        self.assertEqual(status, 200)
        self.assertEqual(saved["state"], "connected")
        self.assertEqual(
            operator("GET", listing, cookie=cookie)[2]["items"][0]["selected_version"], 1
        )
        native = operator("GET", "/operator/v1/usage-costs?page=1&limit=1", cookie=cookie)
        self.assertEqual(native[0], 200)
        self.assertEqual(operator("GET", "/operator/v1/usage-costs?page=1&limit=1")[0], 401)
        self.assertEqual(operator("GET", "/operator/v1/models", cookie=cookie)[0], 200)
        self.assertEqual(operator("GET", "/operator/v1/principals", cookie=cookie)[0], 200)
        demo_path = "/operator/v1/demo-workspace?collection=team&story=oren_opportunity"
        self.assertEqual(operator("GET", demo_path)[0], 401)
        status, _, demo = operator("GET", demo_path, cookie=cookie)
        self.assertEqual(
            (status, demo["identity"], demo["collection"]),
            (200, "dev09-team-scripted-cost-demo-v2", "team"),
        )
        report_path = "/operator/v1/integration/report?dataset_id=" + self.dataset
        status, _, report = operator("GET", report_path, cookie=cookie)
        self.assertEqual(
            (status, report["integration_version"], report["attempt_count"]), (200, "3", 0)
        )
        self.assertEqual(operator("GET", report_path + "&actor_id=svc.demo", cookie=cookie)[0], 200)
        self.assertEqual(operator("GET", report_path + "&export=json", cookie=cookie)[2], report)
        status, _, exported = operator(
            "GET", "/operator/v1/integration/export?dataset_id=" + self.dataset, cookie=cookie
        )
        self.assertEqual(
            (status, exported["integration_version"], len(exported["events"])), (200, "3", 0)
        )
        self.assertEqual(operator("GET", report_path)[0], 401)
        conn = http.client.HTTPConnection("127.0.0.1", operator_port, timeout=3)
        try:
            conn.request(
                "GET",
                report_path + "&export=csv",
                headers={"Host": f"127.0.0.1:{operator_port}", "Cookie": cookie},
            )
            csv_response = conn.getresponse()
            self.assertEqual(csv_response.status, 200)
            self.assertIn("attempt_id", csv_response.read().decode().splitlines()[0])
        finally:
            conn.close()
        self.assertEqual(operator("GET", listing)[0], 401)
        self.registry.mutate(
            "owner.local",
            {
                "operation_id": "op.reader.create",
                "action": "create_principal",
                "subject": "user.reader",
                "expected_revision": 0,
                "data": {"display_name": "Reader", "kind": "human", "owner": "owner.local"},
            },
        )
        _, reader_token = self.registry.provision_credential(
            "owner.local", "user.reader", 1, "op.reader.provision"
        )
        self.registry.mutate(
            "owner.local",
            {
                "operation_id": "op.reader.activate",
                "action": "principal_state",
                "subject": "user.reader",
                "expected_revision": 2,
                "data": {"status": "active", "reason": "controlled"},
            },
        )
        status, headers, reader_login = operator(
            "POST", "/operator/v1/login", {"password": reader_token}
        )
        self.assertEqual(status, 200)
        reader_cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.assertEqual(operator("GET", listing, cookie=reader_cookie)[0], 404)
        self.assertEqual(operator("GET", report_path, cookie=reader_cookie)[0], 404)
        self.assertEqual(
            operator(
                "POST",
                "/operator/v1/integration/connections",
                body,
                reader_cookie,
                reader_login["csrf"],
            )[0],
            403,
        )
        api_port = 0
        api = serve_api("127.0.0.1", api_port, SimpleNamespace(registry=self.registry))
        api_port = api.server_port
        api_thread = threading.Thread(target=api.serve_forever)
        api_thread.start()
        self.addCleanup(lambda: (api.shutdown(), api.server_close(), api_thread.join(timeout=3)))

        def resolve(token):
            conn = http.client.HTTPConnection("127.0.0.1", api_port, timeout=3)
            try:
                conn.request(
                    "GET",
                    "/integration/v3/credentials/"
                    + pending["account_id"]
                    + "/resolve?dataset_id="
                    + self.dataset
                    + "&purpose=vega-provider-dispatch&"
                    "operation_family=generation&model_id=claude-opus-4-8",
                    headers={
                        "Authorization": "Bearer " + token,
                        "EzLLMRouter-Integration-Version": "3",
                    },
                )
                response = conn.getresponse()
                return response.status, json.loads(response.read())
            finally:
                conn.close()

        self.assertEqual(resolve(self.consumer_token)[1]["credential_version"], 1)
        self.assertEqual(resolve(reader_token)[0], 404)


if __name__ == "__main__":
    unittest.main()
