"""Configurable identities, forwarding boundaries and fixture packaging."""

from dataclasses import replace
from contextlib import closing
from importlib.util import find_spec
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from ezllmrouter_server.external_identity import IdentityLookup
from ezllmrouter_server.identity import InstanceIdentity
from ezllmrouter_server.integration_bootstrap import ensure_services
from ezllmrouter_server.integration_local import DEST, NoSendAuthority
from ezllmrouter_server.integration_accounting import IntegrationError
from ezllmrouter_server.registry import Registry
from ezllmrouter_server.store import SQLiteStore
from tests.operator_console import test_integration_credentials as credentials
from tools.gateway.stage import source_mapping

ROOT = Path(__file__).resolve().parents[2]


class IdentityPolicyTests(unittest.TestCase):
    def test_nondefault_owner_task_and_consumer_bootstrap_survive_restart(self):
        identity = InstanceIdentity("owner.example", "class.example", "svc.example", "provider-use")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for _ in range(2):
                with closing(SQLiteStore(root / "service.sqlite")) as store:
                    registry = Registry(
                        store,
                        NoSendAuthority(),
                        identity=identity,
                        legacy_destination=DEST,
                        legacy_token="synthetic-test-token",
                        legacy_trusted={
                            "principal_id": "svc.bootstrap",
                            "charging_owner_id": "team.bootstrap",
                        },
                    )
                    ensure_services(registry, root / "secrets")
                    self.assertEqual(registry.principal("owner.example")["owner"], "owner.example")
                    self.assertIsNone(registry.principal("owner.local"))
                    self.assertIsNone(registry.principal("svc.vega.credential-consumer"))
                    self.assertEqual(registry.principal("svc.example")["status"], "active")
                    self.assertEqual(
                        registry.model(DEST["configuration_ref"])["task_classes"], ["class.example"]
                    )

    def test_reopening_with_a_different_owner_rejects_without_renaming_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            with closing(SQLiteStore(Path(temporary) / "service.sqlite")) as store:
                Registry(
                    store,
                    NoSendAuthority(),
                    legacy_destination=DEST,
                    legacy_token="token",
                    legacy_trusted={
                        "principal_id": "svc.bootstrap",
                        "charging_owner_id": "team.bootstrap",
                    },
                )
                before = list(store.db.iterdump())
                with self.assertRaisesRegex(ValueError, "configured owner"):
                    Registry(
                        store, NoSendAuthority(), identity=InstanceIdentity(owner_id="owner.other")
                    )
                self.assertEqual(list(store.db.iterdump()), before)

    def test_credential_release_uses_configured_principal_and_purpose(self):
        fixture = credentials.CredentialTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        registry = fixture.registry
        registry.identity = replace(
            registry.identity,
            credential_consumer_id="svc.example",
            credential_release_purpose="provider-use",
        )
        for request in (
            {
                "operation_id": "op.custom.create",
                "action": "create_principal",
                "subject": "svc.example",
                "expected_revision": 0,
                "data": {
                    "display_name": "Custom consumer",
                    "kind": "service",
                    "owner": "owner.local",
                    "role": "ordinary",
                },
            },
        ):
            registry.mutate("owner.local", request)
        registry.provision_credential("owner.local", "svc.example", 1, "op.custom.credential")
        registry.mutate(
            "owner.local",
            {
                "operation_id": "op.custom.activate",
                "action": "principal_state",
                "subject": "svc.example",
                "expected_revision": 2,
                "data": {"status": "active", "reason": "test"},
            },
        )
        pending = fixture.connect()
        fixture.credentials.save(
            fixture.owner,
            pending["account_id"],
            {
                "dataset_id": fixture.dataset,
                "expected_revision": pending["revision"],
                "selected_models": ["claude-opus-4-8"],
                "allowed_operations": [],
            },
        )
        custom = registry.principal("svc.example")
        args = (fixture.dataset, pending["account_id"], "claude-opus-4-8", "generation")
        for actor, purpose in (
            (fixture.consumer, "provider-use"),
            (custom, "vega-provider-dispatch"),
        ):
            with self.assertRaises(IntegrationError):
                fixture.credentials.resolve_for(actor, *args, purpose)
        released = fixture.credentials.resolve_for(custom, *args, "provider-use")
        self.assertEqual(released["api_key"], "known-fixture-api-key-0001")


class IdentityLookupTests(unittest.TestCase):
    def test_no_cookie_match_makes_no_connection_and_prefixes_are_not_allowlisted(self):
        with patch("ezllmrouter_server.external_identity.HTTPConnection") as connect:
            self.assertIsNone(
                IdentityLookup("http://127.0.0.1:8080", ("session",))("session_other=value")
            )
        connect.assert_not_called()

    def test_only_exact_cookie_names_leave_the_service_and_connection_closes(self):
        connection = Mock()
        connection.getresponse.return_value.status = 200
        connection.getresponse.return_value.read.return_value = (
            b'{"user":{"id":"user.example","name":"Example","private":"hidden"}}'
        )
        with patch("ezllmrouter_server.external_identity.HTTPSConnection", return_value=connection):
            result = IdentityLookup("https://identity.example:8443", ("display_session",))(
                "display_session=allowed; router_session=private; display_session_suffix=no"
            )
        self.assertEqual(result, {"id": "user.example", "name": "Example"})
        connection.request.assert_called_once_with(
            "GET", "/api/me", headers={"Cookie": "display_session=allowed"}
        )
        connection.close.assert_called_once()

    def test_lookup_failures_and_malformed_or_oversized_bodies_return_no_user(self):
        for body in (
            b"[]",
            b'{"user":[]}',
            b'{"user":{"id":1,"name":"Example"}}',
            b"{" + b" " * 4096,
        ):
            connection = Mock()
            connection.getresponse.return_value.status = 200
            connection.getresponse.return_value.read.return_value = body
            with patch(
                "ezllmrouter_server.external_identity.HTTPConnection", return_value=connection
            ):
                self.assertIsNone(
                    IdentityLookup("http://localhost:8080", ("session",))("session=value")
                )
            connection.close.assert_called_once()

    def test_forwarding_requires_explicit_safe_configuration(self):
        for origin, names in (
            ("http://identity.example", ("session",)),
            ("https://identity.example/api", ("session",)),
            ("https://user:password@identity.example", ("session",)),
            ("https://identity.example", ()),
            ("https://identity.example", ("session*",)),
        ):
            with self.assertRaises(ValueError):
                IdentityLookup(origin, names)


class FixturePackagingTests(unittest.TestCase):
    def test_synthetic_service_is_only_available_from_explicit_tools_package(self):
        self.assertIsNone(find_spec("ezllmrouter_server.successor_service"))
        from tools.synthetic.successor_service import SuccessorService

        self.assertEqual(SuccessorService.__module__, "tools.synthetic.successor_service")
        default = source_mapping(ROOT)
        explicit = source_mapping(ROOT, fixtures=True)
        self.assertFalse(any(source.startswith("tools/synthetic/") for source, _ in default))
        self.assertTrue(any(source.startswith("tools/synthetic/") for source, _ in explicit))
