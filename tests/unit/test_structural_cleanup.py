"""Structural changes preserve stored identity, wire behavior and adopted fixtures."""

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from deploy.local import prepare
from ezllmrouter_server.database import Query
from ezllmrouter_server.errors import RequestError
from ezllmrouter_server.formatting import earliest_timestamp, utc_timestamp
from ezllmrouter_server.identity import DEFAULT_IDENTITY, InstanceIdentity, resolve_identity
from ezllmrouter_server.operator_http.handler import OperatorHandler
from ezllmrouter_server.operator_http.registry_routes import RegistryRoutes
from ezllmrouter_server.operator_http.routing import ROUTER
from ezllmrouter_server.registry import Registry
from ezllmrouter_server.store import SQLiteStore, encode
from ezllmrouter_server.web import serve
from tests.operator_console.test_registry import Authority, DEST, TOKEN, TRUSTED
from tests.operator_console.test_user_management_web import MemoryServer
from tests.unit import test_http_structure as http_fixtures
from tools.type_audit import error_counts, regressions

ROOT = Path(__file__).resolve().parents[2]


class StoredIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "store.sqlite"

    def registry(self, store, **kwargs):
        return Registry(
            store,
            Authority(),
            legacy_destination=DEST,
            legacy_token=TOKEN,
            legacy_trusted=TRUSTED,
            **kwargs,
        )

    def test_new_default_is_persisted_and_reopen_rejects_a_rename(self):
        with self.owned_store() as store:
            registry = self.registry(store)
            self.assertEqual(registry.identity, DEFAULT_IDENTITY)
            self.assertEqual(
                registry.identity.credential_consumer_id, "svc.ezllmrouter.credential-consumer"
            )
            before = registry.version()
        with self.owned_store() as store:
            registry = self.registry(store)
            self.assertEqual(registry.identity, DEFAULT_IDENTITY)
            self.assertEqual(registry.version(), before)
            with self.assertRaisesRegex(ValueError, "persisted instance"):
                self.registry(store, identity=InstanceIdentity(credential_consumer_id="svc.other"))
            self.assertEqual(resolve_identity(store.database), registry.identity)

    def test_legacy_consumer_is_adopted_without_renaming_a_principal(self):
        with self.owned_store() as store:
            registry = self.registry(store)
            record = {
                "principal_id": "svc.vega.credential-consumer",
                "kind": "service",
                "status": "active",
                "role": "credential_consumer",
            }

            def legacy():
                store.database.execute(
                    Query("DELETE FROM registry_meta WHERE key='instance_identity'")
                )
                store.database.execute(
                    Query("INSERT INTO registry_principals VALUES (?,?)"),
                    (record["principal_id"], encode(record)),
                )

            store.database.transaction(legacy)
            before = registry.version()
        with self.owned_store() as store:
            registry = self.registry(store)
            self.assertEqual(registry.identity.credential_consumer_id, record["principal_id"])
            self.assertEqual(registry.identity.credential_release_purpose, "vega-provider-dispatch")
            self.assertEqual(registry.principal(record["principal_id"]), record)
            self.assertIsNone(registry.principal(DEFAULT_IDENTITY.credential_consumer_id))
            self.assertEqual(registry.version(), before)

    def test_custom_identity_survives_default_construction_and_rejects_overrides(self):
        identity = InstanceIdentity(
            credential_consumer_id="svc.custom.consumer",
            credential_release_purpose="custom.dispatch",
        )
        with self.owned_store() as store:
            self.registry(store, identity=identity)
        with self.owned_store() as store:
            self.assertEqual(self.registry(store).identity, identity)
            self.assertEqual(
                resolve_identity(store.database, overrides={"owner_id": identity.owner_id}),
                identity,
            )
            with self.assertRaises(ValueError):
                resolve_identity(
                    store.database, overrides={"credential_release_purpose": "new.purpose"}
                )
            raw = store.database.execute(
                Query("SELECT value FROM registry_meta WHERE key='instance_identity'")
            ).fetchone()[0]
            self.assertEqual(json.loads(raw), asdict(identity))

    def test_custom_owner_policy_survives_restart_without_identity_flags(self):
        from ezllmrouter_server import integration_local

        identity = InstanceIdentity(owner_id="owner.custom")
        with self.owned_store() as store:
            self.registry(store, identity=identity)
        root = Path(self.temporary.name)
        policy = {
            "mode": "approved",
            "policy_id": "policy.custom",
            "approved_by": identity.owner_id,
            "max_days_by_class": {"low": 1},
        }
        path = root / "policy.json"
        path.write_text(json.dumps(policy))
        args = SimpleNamespace(
            db=self.path,
            feature_policy_file=path,
            secrets_dir=root,
            api_port=48760,
            owner_id=None,
            task_class=None,
            credential_consumer_id=None,
            credential_release_purpose=None,
            accounting_retention_days=None,
        )
        parser = Mock()
        parser.error.side_effect = AssertionError("policy rejected")
        loaded = integration_local._feature_policy(args, None, parser)

        class BeforeListener(Exception):
            pass

        with (
            patch.object(integration_local, "_bootstrap_accounting", return_value="p" * 40),
            patch.object(integration_local, "UserManager"),
            patch.object(integration_local, "api_serve", side_effect=BeforeListener) as api,
            self.assertRaises(BeforeListener),
        ):
            integration_local._run_service(args, DEFAULT_IDENTITY, None, loaded, None, parser)
        actual = api.call_args.args[2].registry
        self.assertEqual(actual.identity, identity)
        self.assertEqual(actual.integration.feature_policy, policy)
        parser.error.assert_not_called()

    def owned_store(self):
        from contextlib import closing

        return closing(SQLiteStore(self.path))


class ProfileIdentityTests(unittest.TestCase):
    def setUp(self):
        from tests.unit.test_deployment_safety import profile

        self.profile = profile
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state = Path(temporary.name)
        replacement = patch.object(profile, "STATE", self.state)
        replacement.start()
        self.addCleanup(replacement.stop)

    def test_existing_project_marker_is_used_by_compose(self):
        legacy = "ezllmrouter-dev06-local"
        (self.state / "PROFILE-OWNER.json").write_text(
            json.dumps({"project": legacy, "root": str(self.profile.ROOT)})
        )
        command = self.profile.compose_args("ps")
        self.assertEqual(command[command.index("--project-name") + 1], legacy)
        self.assertEqual(self.profile.PROJECT, "ezllmrouter-local")

    def test_foreign_marker_is_rejected_before_a_docker_command(self):
        (self.state / "PROFILE-OWNER.json").write_text(
            json.dumps({"project": "ezllmrouter-local", "root": "/other/checkout"})
        )
        with patch.object(self.profile, "command") as command, self.assertRaises(RuntimeError):
            self.profile.ensure_owner({})
        command.assert_not_called()

    def test_unowned_legacy_resources_block_a_new_project(self):
        with (
            patch.object(
                self.profile,
                "command",
                side_effect=[("ezllmrouter-dev06-local-service-1\n", 0), ("", 0)],
            ),
            self.assertRaisesRegex(RuntimeError, "resource collision"),
        ):
            self.profile.ensure_owner({})
        self.assertFalse((self.state / "PROFILE-OWNER.json").exists())

    def test_deployment_preparation_rejects_dirty_source_before_building(self):
        with (
            patch.object(prepare, "source_dirty", return_value=True),
            patch.object(prepare.subprocess, "run") as run,
            self.assertRaisesRegex(SystemExit, "commit runtime source"),
        ):
            prepare.main()
        run.assert_not_called()


class TimestampAndFixtureTests(unittest.TestCase):
    def test_timestamp_selection_compares_instants_and_preserves_stored_bytes(self):
        earlier = "2030-01-01T00:00:00Z"
        later = "2029-12-31T20:00:00-05:00"
        self.assertEqual(earliest_timestamp(later, earlier), earlier)
        self.assertEqual(earliest_timestamp(None, later), later)
        self.assertIsNone(earliest_timestamp(None))
        with self.assertRaises(ValueError):
            earliest_timestamp("2030-01-01T00:00:00")
        self.assertEqual(
            utc_timestamp(datetime(2030, 1, 1, tzinfo=timezone.utc), precise=True),
            "2030-01-01T00:00:00.000000Z",
        )

    def test_runtime_fixture_copies_preserve_the_adopted_golden_bytes(self):
        for original, staged in (
            ("tests/development_slice/fixture.json", "execution.json"),
            ("tests/development_slice/request.json", "request.json"),
            ("tests/tool_cycle/scenarios.json", "tool-cycle.json"),
            ("tools/gateway/evidence/dev05_fixture.json", "controlled-execution.json"),
        ):
            with self.subTest(fixture=staged):
                self.assertEqual(
                    (ROOT / original).read_bytes(),
                    (ROOT / "deploy/local/inputs/fixtures" / staged).read_bytes(),
                )


class RouteBoundaryTests(unittest.TestCase):
    exchange = http_fixtures.HTTPFramingTests.exchange

    def test_nonobject_integration_body_is_rejected_before_ledger_dispatch(self):
        ledger = Mock()
        coordinator = SimpleNamespace(
            registry=SimpleNamespace(
                integration=ledger, credential_principal=lambda _: {"principal_id": "owner.local"}
            )
        )
        with patch("ezllmrouter_server.web.BoundedHTTPServer", MemoryServer):
            server = serve("127.0.0.1", 48761, coordinator)
        request = b"POST /integration/v3/snapshots HTTP/1.1\r\nHost: 127.0.0.1:48761\r\nAuthorization: Bearer synthetic\r\nEzLLMRouter-Integration-Version: 3\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n[]"
        reply = self.exchange(server, request)
        self.assertIn(b"400", reply.split(b"\r\n", 1)[0])
        self.assertIn(b"SCHEMA_INVALID", reply)
        ledger.append_snapshot.assert_not_called()

    def test_route_roles_reject_before_calling_the_protected_handler(self):
        route = ROUTER.resolve("GET", "/operator/v1/providers", query=False, available={"registry"})
        handler = SimpleNamespace(_fail=Mock(), get_registry_providers=Mock())
        self.assertTrue(
            OperatorHandler._dispatch(
                handler, route, "resource", session=("id", {"role": "ordinary"})
            )
        )
        handler._fail.assert_called_once_with(403, "OPERATOR_REQUIRED")
        handler.get_registry_providers.assert_not_called()

    def test_typed_registry_rejection_retains_its_public_code(self):
        registry = Mock()
        registry.mutate.side_effect = RequestError("POLICY_DENIED", 403)
        handler = SimpleNamespace(
            application=SimpleNamespace(registry=registry),
            _registry=registry,
            _fail=lambda status, code: (status, code),
            _send=Mock(),
        )
        result = RegistryRoutes.post_operator_v1_registry(
            handler,
            None,
            ("id", {"role": "registry_admin", "principal_id": "owner.local"}),
            {},
            None,
        )
        self.assertEqual(result, (403, "POLICY_DENIED"))
        handler._send.assert_not_called()


class TypeAuditTests(unittest.TestCase):
    def test_audit_counts_errors_without_counting_notes(self):
        output = "server/example.py:1: error: bad [assignment]\nserver/example.py:1: note: detail\nserver/example.py:2:7: error: another [arg-type]\n"
        self.assertEqual(error_counts(output), {"server/example.py": 2})

    def test_new_and_increased_debt_fail_while_reductions_pass(self):
        self.assertEqual(regressions({"known.py": 2}, {"known.py": 1}), [])
        self.assertEqual(len(regressions({"known.py": 2}, {"known.py": 3, "new.py": 1})), 2)
