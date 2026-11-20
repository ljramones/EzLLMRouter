"""Actual operator HTTP management boundaries, including current roles."""

import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]


from ezllmrouter_server.operator_projection import OperatorProjection
from ezllmrouter_server.operator_web import serve
from ezllmrouter_server.registry import Registry
from ezllmrouter_server.store import SQLiteStore
from deploy.local import catalogue_import as catalogue_import


class Authority:
    def __init__(self):
        self.gate = threading.RLock()
        self.epoch = 0


class Runner:
    def run(self, *_):
        raise AssertionError("registry reads/writes must not launch")


class ValidationRunner:
    principal_id = "svc.demo"

    def __init__(self):
        self.calls = []

    def run(self, configuration_ref, operation_id, max_output_tokens, on_handle):
        self.calls.append((configuration_ref, operation_id, max_output_tokens))
        on_handle("submission.provider.validation")
        return "completed"


class RegistryWebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(Path(self.tmp.name) / "store.sqlite")
        fixture = json.loads((ROOT / "tools/gateway/evidence/dev05_fixture.json").read_text())
        self.registry = Registry(
            self.store,
            Authority(),
            legacy_destination={
                **fixture["destination"],
                "service": "litellm.dev04",
                "endpoint": "127.0.0.1",
            },
            legacy_token="test-service-token-for-registry-web-00000000",
            legacy_trusted=fixture["trusted_context"],
        )
        self.projection = OperatorProjection(self.store, "svc.demo")
        self.provider_runner = ValidationRunner()
        self.port = 0
        self.origin = f"http://127.0.0.1:{self.port}"
        self.server = serve(
            "127.0.0.1",
            self.port,
            projection=self.projection,
            runner=Runner(),
            password="p" * 40,
            fixture=fixture,
            build={"commit": "test"},
            web_root=ROOT / "web",
            worker_probe=lambda: {"state": "live"},
            sender_status=lambda: {"state": "live"},
            registry=self.registry,
            provider_validation=self.provider_runner,
        )
        self.port = self.server.server_port
        self.origin = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.server.operator_jobs.shutdown(wait=True)
        self.store.close()
        self.tmp.cleanup()

    def request(self, method, path, body=None, cookie=None, csrf=None, origin=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        headers = {"Host": f"127.0.0.1:{self.port}"}
        if origin and method == "POST":
            headers["Origin"] = self.origin
        if cookie:
            headers["Cookie"] = cookie
        if csrf:
            headers["X-EzLLMRouter-CSRF"] = csrf
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            conn.request(method, path, json.dumps(body) if body is not None else None, headers)
            result = conn.getresponse()
            data = json.loads(result.read())
            return result.status, dict(result.getheaders()), data
        finally:
            conn.close()

    def login(self, secret):
        status, headers, data = self.request("POST", "/operator/v1/login", {"password": secret})
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0], data["csrf"]

    def change(self, cookie, csrf, operation, action, subject, expected, data):
        return self.request(
            "POST",
            "/operator/v1/registry",
            {
                "operation_id": operation,
                "action": action,
                "subject": subject,
                "expected_revision": expected,
                "data": data,
            },
            cookie,
            csrf,
        )

    def test_management_is_durable_idempotent_and_role_checked(self):
        owner, csrf = self.login("p" * 40)
        self.assertEqual(self.request("GET", "/operator/v1/models", cookie=owner)[0], 200)
        self.assertEqual(
            self.request(
                "GET",
                "/operator/v1/access/explain?principal_id=svc.demo&configuration_ref=cfg.demo&purpose=execution&task_class=class.demo",
                cookie=owner,
            )[2]["allowed"],
            True,
        )
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 0)

        command = (
            "op.model",
            "create_model",
            "cfg.alt",
            0,
            {
                "display_name": "Alt",
                "model": "model.demo.alt",
                "model_version": "v1",
                "owner": "owner.local",
                "capabilities": ["text"],
                "purposes": ["execution"],
                "task_classes": ["class.demo"],
            },
        )
        self.assertEqual(self.change(owner, csrf, *command)[0], 200)
        self.assertEqual(self.change(owner, csrf, *command)[0], 200)
        self.assertEqual(
            self.change(owner, csrf, *command[:-1], {**command[-1], "display_name": "Changed"})[0],
            409,
        )
        self.assertEqual(
            self.request("GET", "/operator/v1/models/cfg.alt", cookie=owner)[2]["model"][
                "revision"
            ],
            1,
        )
        self.assertEqual(
            self.change(
                owner,
                None,
                "op.no-csrf",
                "create_principal",
                "user.reader",
                0,
                {"display_name": "Reader", "kind": "human", "owner": "owner.local"},
            )[0],
            403,
        )
        self.assertEqual(
            self.change(
                owner,
                csrf,
                "op.reader",
                "create_principal",
                "user.reader",
                0,
                {"display_name": "Reader", "kind": "human", "owner": "owner.local"},
            )[0],
            200,
        )
        status, _, provision = self.request(
            "POST",
            "/operator/v1/provision",
            {"operation_id": "op.provision", "principal_id": "user.reader", "expected_revision": 1},
            owner,
            csrf,
        )
        self.assertEqual(status, 200)
        secret = provision["one_time_credential"]
        self.assertTrue(secret)
        self.assertIsNone(
            self.request(
                "POST",
                "/operator/v1/provision",
                {
                    "operation_id": "op.provision",
                    "principal_id": "user.reader",
                    "expected_revision": 1,
                },
                owner,
                csrf,
            )[2]["one_time_credential"]
        )
        self.assertEqual(
            self.change(
                owner,
                csrf,
                "op.activate",
                "principal_state",
                "user.reader",
                2,
                {"status": "active", "reason": "Test"},
            )[0],
            200,
        )
        self.assertEqual(
            self.change(
                owner, csrf, "op.role", "set_role", "user.reader", 3, {"role": "read_only_operator"}
            )[0],
            200,
        )
        reader, reader_csrf = self.login(secret)
        self.assertEqual(self.request("GET", "/operator/v1/models", cookie=reader)[0], 200)
        self.assertEqual(
            self.change(
                reader,
                reader_csrf,
                "op.denied",
                "model_state",
                "cfg.alt",
                1,
                {"status": "disabled", "reason": "No authority"},
            )[0],
            403,
        )
        self.assertEqual(
            self.request(
                "POST", "/operator/v1/demos/text", {"operation_id": "op.demo"}, reader, reader_csrf
            )[0],
            403,
        )
        self.assertEqual(
            self.change(
                owner,
                csrf,
                "op.suspend",
                "principal_state",
                "user.reader",
                4,
                {"status": "suspended", "reason": "Test"},
            )[0],
            200,
        )
        self.assertEqual(self.request("GET", "/operator/v1/models", cookie=reader)[0], 401)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 0)

    def test_provider_validation_requires_explicit_allowed_one_use_request(self):
        owner, csrf = self.login("p" * 40)
        request = {
            "operation_id": "op.provider.validation",
            "connection_id": "conn.provider.test",
            "connection_revision": 4,
            "configuration_ref": "cfg.provider.test",
            "configuration_revision": 3,
            "max_output_tokens": 16,
            "acknowledge_external_send": True,
        }
        path = "/operator/v1/provider-validation"
        self.assertEqual(self.request("POST", path, request, owner, csrf)[0], 400)
        self.assertEqual(self.provider_runner.calls, [])
        self.registry.provider_execution_ready = True
        self.registry.connection = lambda _id: {
            "revision": 4,
            "status": "active",
            "credential_state": "present",
        }
        self.registry.model = lambda _ref: {
            "revision": 3,
            "destination": {
                "connection_id": "conn.provider.test",
                "adapter_id": "openai.responses.v1",
            },
        }
        allowed = False
        self.registry.explain = lambda *_: {"allowed": allowed}
        self.assertEqual(self.request("POST", path, request, owner, csrf)[0], 409)
        self.assertEqual(self.provider_runner.calls, [])
        allowed = True
        self.assertEqual(
            self.request(
                "POST", path, {**request, "acknowledge_external_send": False}, owner, csrf
            )[0],
            400,
        )
        self.assertEqual(self.request("POST", path, request, owner, None)[0], 403)
        self.assertEqual(self.request("POST", path, request, owner, csrf, origin=False)[0], 403)
        status, _, first = self.request("POST", path, request, owner, csrf)
        self.assertEqual(status, 200)
        self.assertEqual(first["state"], "completed")
        self.assertEqual(first["submission_id"], "submission.provider.validation")
        self.assertEqual(
            self.provider_runner.calls, [("cfg.provider.test", "op.provider.validation", 16)]
        )
        self.assertEqual(self.request("POST", path, request, owner, csrf)[2], first)
        self.assertEqual(
            self.provider_runner.calls, [("cfg.provider.test", "op.provider.validation", 16)]
        )
        self.assertEqual(
            self.request("POST", path, {**request, "max_output_tokens": 17}, owner, csrf)[0], 409
        )
        self.assertEqual(
            self.request(
                "GET", "/operator/v1/provider-validations/op.provider.validation", cookie=owner
            )[2],
            first,
        )
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 0)

    def test_source_inventory_read_and_permission_write_are_authorized(self):
        owner, csrf = self.login("p" * 40)
        self.registry.controlled_provider_proof = True
        self.assertEqual(
            self.change(
                owner,
                csrf,
                "op.source.web.create",
                "create_connection",
                "conn.source-web",
                0,
                {
                    "display_name": "Controlled lab",
                    "adapter_id": "vllm.openai-compatible.v1",
                    "settings": {
                        "origin": "https://localhost:8766",
                        "location": "office_lab",
                        "site": "Lab A",
                    },
                    "owner": "owner.local",
                },
            )[0],
            200,
        )
        observation = {
            "operation_id": "op.source.web.inventory",
            "connection_id": "conn.source-web",
            "connection_revision": 1,
            "credential_version": 0,
            "adapter_id": "vllm.openai-compatible.v1",
            "operation": "inventory",
            "scope": "model_inventory",
            "observer": "controlled_test",
            "observed_at": "2026-10-22T00:00:00Z",
            "expires_at": "2026-10-22T00:05:00Z",
            "state": "observed",
            "reason": "inventory_not_inference_entitlement",
            "models": ["model-one"],
            "has_more": False,
        }
        self.store.db.execute(
            "INSERT INTO registry_observations VALUES (?,?,?)",
            (observation["operation_id"], "conn.source-web", json.dumps(observation)),
        )
        path = "/operator/v1/connections/conn.source-web/inventory"
        self.assertEqual(self.request("GET", path)[0], 401)
        status, _, inventory = self.request("GET", path, cookie=owner)
        self.assertEqual(status, 200)
        self.assertEqual(inventory["items"][0]["serving_id"], "model-one")
        self.assertFalse(inventory["items"][0]["allowed"])
        data = {"allowed": True, "items": [{"serving_id": "model-one", "expected_revision": 0}]}
        self.assertEqual(
            self.change(
                owner,
                None,
                "op.source.web.denied",
                "set_source_permissions",
                "conn.source-web",
                0,
                data,
            )[0],
            403,
        )
        self.assertEqual(
            self.change(
                owner,
                csrf,
                "op.source.web.unknown",
                "set_source_permissions",
                "conn.source-web",
                0,
                {
                    "allowed": True,
                    "items": [{"serving_id": "future-model", "expected_revision": 0}],
                },
            )[0],
            400,
        )
        self.assertEqual(
            self.change(
                owner,
                csrf,
                "op.source.web.allow",
                "set_source_permissions",
                "conn.source-web",
                0,
                data,
            )[0],
            200,
        )
        self.assertTrue(self.request("GET", path, cookie=owner)[2]["items"][0]["allowed"])
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 0)

    def test_researched_catalogue_import_uses_admin_guard_and_adds_no_send(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            conn.request("GET", "/catalogue_view.js", headers={"Host": f"127.0.0.1:{self.port}"})
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn(b"Catalogued", response.read())
        finally:
            conn.close()
        seed = catalogue_import.seed_data()
        entry = seed["models"][0]
        source_map = {source["id"]: source for source in seed["sources"]}
        data = {"entry": entry, "sources": [source_map[key] for key in entry["source_refs"]]}
        request = {
            "operation_id": "op.catalogue.unauthorized",
            "action": "import_catalogue",
            "subject": "catalogue." + entry["catalogue_key"],
            "expected_revision": 0,
            "data": data,
        }
        self.assertEqual(self.request("POST", "/operator/v1/registry", request)[0], 401)
        owner, csrf = self.login("p" * 40)
        self.assertEqual(self.request("POST", "/operator/v1/registry", request, owner)[0], 403)
        self.assertEqual(
            self.request("POST", "/operator/v1/registry", request, owner, csrf, origin=False)[0],
            403,
        )
        client = catalogue_import.OperatorClient("p" * 40, self.port)
        before = self.registry.version()
        result = catalogue_import.import_catalogue(client, seed)
        self.assertEqual(result["catalogue_entries"], 12)
        self.assertEqual(self.registry.principal("owner.local")["display_name"], "Larry Mitchell")
        self.assertEqual(self.registry.version(), before + 13)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 0)
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM registry_grants").fetchone()[0], 1
        )
        again = catalogue_import.import_catalogue(client, seed)
        self.assertEqual(again["catalogue_entries"], 12)
        self.assertEqual(self.registry.version(), before + 13)
        ref = "catalogue." + entry["catalogue_key"]
        self.assertEqual(
            self.request("GET", "/operator/v1/models/" + ref, cookie=owner)[2]["readiness"],
            "not_connected",
        )
        self.assertEqual(
            self.change(owner, csrf, "op.catalogue.stale", "import_catalogue", ref, 2, data)[0], 409
        )
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 0)

    def test_manual_crud_http_authority_revision_and_no_traffic(self):
        owner, csrf = self.login("p" * 40)
        price = {
            "snapshot_id": "browser.test.v1",
            "source_title": "Disposable reference",
            "source_url": "https://example.org/prices",
            "bands": [
                {
                    "label": "Test",
                    "conditions": {},
                    "rates_usd_per_1000000_tokens": {
                        "input_uncached": "1",
                        "output": "2",
                        "input_cached": None,
                    },
                }
            ],
        }
        model = {
            "display_name": "Disposable browser model",
            "vendor": "Test vendor",
            "family": "Test family",
            "api_model_id": "test-api",
            "model_version": "v1",
            "owner": "owner.local",
            "capabilities": ["text"],
            "context_window": None,
            "max_output": None,
            "notes": "Disposable",
            "price": price,
        }
        ref = "catalogue.operator.browser-test"
        self.assertEqual(
            self.change(owner, csrf, "op.crud.model", "register_catalogue", ref, 0, model)[0], 200
        )
        self.assertEqual(
            self.change(owner, csrf, "op.crud.model", "register_catalogue", ref, 0, model)[0], 200
        )
        self.assertEqual(
            self.change(
                owner,
                csrf,
                "op.crud.model",
                "register_catalogue",
                ref,
                0,
                {**model, "display_name": "Altered"},
            )[0],
            409,
        )
        self.assertEqual(
            self.change(
                owner,
                csrf,
                "op.crud.stale",
                "edit_catalogue_model",
                ref,
                0,
                {
                    key: model[key]
                    for key in (
                        "display_name",
                        "vendor",
                        "family",
                        "owner",
                        "capabilities",
                        "context_window",
                        "max_output",
                        "notes",
                    )
                },
            )[0],
            409,
        )
        self.assertEqual(
            self.change(
                owner,
                csrf,
                "op.crud.overpost",
                "archive_model",
                ref,
                1,
                {"reason": "test", "purge": True},
            )[0],
            400,
        )
        self.assertEqual(
            self.change(
                owner,
                csrf,
                "op.crud.user",
                "create_principal",
                "user.browser-test",
                0,
                {
                    "display_name": "Disposable test user",
                    "kind": "human",
                    "owner": "owner.local",
                    "role": "ordinary",
                },
            )[0],
            200,
        )
        self.assertEqual(
            self.change(
                owner,
                csrf,
                "op.crud.archive",
                "archive_model",
                ref,
                1,
                {"reason": "Disposable deletion"},
            )[0],
            200,
        )
        self.assertEqual(
            self.change(
                owner,
                csrf,
                "op.crud.revoke",
                "principal_state",
                "user.browser-test",
                1,
                {"status": "revoked", "reason": "Disposable deletion"},
            )[0],
            200,
        )
        self.assertEqual(
            self.request("GET", "/operator/v1/models/" + ref, cookie=owner)[2]["model"]["status"],
            "archived",
        )
        self.assertEqual(
            self.request("GET", "/operator/v1/principals/user.browser-test", cookie=owner)[2][
                "principal"
            ]["status"],
            "revoked",
        )
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
