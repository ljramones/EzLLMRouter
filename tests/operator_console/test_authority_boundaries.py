"""Explicit hostile browser headers and current-principal authority boundaries."""

from email.message import Message
from types import SimpleNamespace

from ezllmrouter_server.operator_http.transport import TransportRoutes
from ezllmrouter_server.repositories.authority import authorized
from tests.operator_console.test_user_management import UserFixture


class AuthorityBoundaryTests(UserFixture):
    def test_unknown_and_ordinary_principals_cannot_authorize_registry_mutations(self):
        self.assertFalse(authorized(self.store.database, "user.absent"))
        user = self.create()
        self.assertFalse(authorized(self.store.database, user["principal_id"]))
        self.update(user, status="suspended")
        self.assertFalse(authorized(self.store.database, user["principal_id"]))
        self.assertTrue(authorized(self.store.database, "owner.local"))

    def test_origin_requires_one_approved_host_and_mutations_require_origin(self):
        cases = [
            ([], None, False, False),
            (["evil.test"], None, False, False),
            (["local.test", "local.test"], None, False, False),
            (["local.test"], None, False, True),
            (["local.test"], None, True, False),
            (["local.test"], "http://evil.test", False, False),
            (["local.test"], "http://local.test", True, True),
        ]
        for hosts, origin, mutation, expected in cases:
            with self.subTest(hosts=hosts, origin=origin, mutation=mutation):
                headers = Message()
                for host in hosts:
                    headers["Host"] = host
                if origin is not None:
                    headers["Origin"] = origin
                handler = SimpleNamespace(
                    headers=headers,
                    application=SimpleNamespace(
                        allowed_hosts={"local.test"}, allowed_origins={"http://local.test"}
                    ),
                )
                self.assertEqual(TransportRoutes._origin_ok(handler, mutation), expected)

    def test_duplicate_missing_wrong_and_unencodable_csrf_are_rejected(self):
        for values, expected in [
            ([], False),
            (["correct", "correct"], False),
            (["wrong"], False),
            (["\ud800"], False),
            (["correct"], True),
        ]:
            with self.subTest(values=values):
                headers = Message()
                for value in values:
                    headers["X-EzLLMRouter-CSRF"] = value
                self.assertEqual(
                    TransportRoutes._csrf_ok(
                        SimpleNamespace(headers=headers), ("token", {"csrf": "correct"})
                    ),
                    expected,
                )
