"""Independent authorization cases for existing operator resource families."""

import csv
import hashlib
import io
import json

from ezllmrouter_server.operator_http.routing import ROUTES
from tests.operator_resource_fixtures import POLICY, ROOT, SECRET, ResourceFixture


def expected(row, role, integration_only):
    if integration_only and row["integration_hidden"] and role != "pending":
        return 404
    return row["statuses"][role]


class ResourceAuthorizationTests(ResourceFixture):
    def assert_reply(self, row, response, status):
        actual, headers, raw = response
        self.assertEqual(actual, status, (row["case"], raw[:250]))
        self.assertEqual(headers["Cache-Control"], "no-store, max-age=0")
        for secret in (SECRET, PASSWORD_CANARY, "DO_NOT_EXPORT", "password_hash", "scrypt$"):
            self.assertNotIn(secret.encode(), raw)
        if actual >= 400:
            self.assertNotIn("items", json.loads(raw))
        return raw

    def test_policy_covers_all_family_bindings_and_reviewed_dispatch_sources(self):
        families = {(route.method, route.path + "*") for route in ROUTES if route.family}
        covered = {(row["method"], row["family"]) for row in POLICY["cases"]}
        self.assertEqual(families, covered)
        self.assertEqual(len(families), 16)
        self.assertEqual(len(POLICY["cases"]), 42)
        self.assertEqual(len({row["case"] for row in POLICY["cases"]}), 42)
        for row in POLICY["cases"]:
            self.assertEqual(set(row["statuses"]), set(POLICY["roles"]))
            self.assertTrue(row["path"].startswith(row["family"][:-1]))
        self.assertEqual(len(POLICY["source_sha256"]), 6)
        for name, digest in POLICY["source_sha256"].items():
            self.assertEqual(
                hashlib.sha256((ROOT / name).read_bytes()).hexdigest(),
                digest,
                "review resource dispatch changes: " + name,
            )

    def test_existing_reads_obey_roles_owners_and_console_modes(self):
        for integration_only in (False, True):
            self.application.integration_only = integration_only
            for row in POLICY["cases"]:
                if row["method"] != "GET":
                    continue
                path, _ = self.request_for(row)
                for role in POLICY["roles"]:
                    with self.subTest(
                        case=row["case"], role=role, integration_only=integration_only
                    ):
                        self.cookie, self.csrf = self.identities[role]
                        before = self.footprint()
                        self.assert_reply(
                            row, self.exchange("GET", path), expected(row, role, integration_only)
                        )
                        self.assertEqual(
                            self.footprint(), before, "read changed data or dispatched work"
                        )

    def test_valid_family_mutations_are_denied_without_any_side_effect(self):
        for integration_only in (False, True):
            self.application.integration_only = integration_only
            for row in POLICY["cases"]:
                if row["method"] == "GET":
                    continue
                path, body = self.request_for(row)
                self.assertTrue(body, row["case"])
                for role in POLICY["roles"]:
                    status = expected(row, role, integration_only)
                    if status < 400:
                        continue
                    with self.subTest(
                        case=row["case"], role=role, integration_only=integration_only
                    ):
                        self.cookie, self.csrf = self.identities[role]
                        before = self.footprint()
                        self.assert_reply(
                            row, self.exchange(row["method"], path, body=body), status
                        )
                        self.assertEqual(
                            self.footprint(),
                            before,
                            "denied mutation changed state, queued work or performed I/O",
                        )

    def positive_writes(self, role):
        self.cookie, self.csrf = self.identities[role]
        for row in POLICY["cases"]:
            if row["method"] == "GET" or row["statuses"][role] >= 400:
                continue
            with self.subTest(case=row["case"], role=role):
                path, body = self.request_for(row)
                before = self.footprint()
                self.assert_reply(
                    row, self.exchange(row["method"], path, body=body), row["statuses"][role]
                )
                after = self.footprint()
                if row["case"] not in {
                    "dataset_create",
                    "account_create",
                    "connector_check",
                    "connector_find",
                }:
                    self.assertGreater(
                        after[0], before[0], "positive write never reached persistence"
                    )
                if row["case"] in {
                    "connector_discover",
                    "credential_connect",
                    "credential_refresh",
                    "credential_replace",
                }:
                    self.assertGreater(
                        after[2], before[2], "positive discovery never reached controlled I/O"
                    )
                if row["case"].startswith("demo_"):
                    self.assertEqual(after[3], before[3] + 1)

    def test_owner_valid_bodies_reach_all_family_write_actions(self):
        self.positive_writes("owner")

    def test_another_admin_can_manage_global_resources_with_valid_bodies(self):
        self.positive_writes("other_admin")

    def test_dataset_lists_reports_exports_and_bindings_remain_owner_scoped(self):
        for role in ("owner", "readonly", "other_admin"):
            self.cookie, self.csrf = self.identities[role]
            listing = json.loads(self.exchange("GET", "/operator/v1/integration/datasets")[2])
            owner = "other_admin" if role == "other_admin" else "owner"
            self.assertEqual(
                {row["dataset_id"] for row in listing["items"]}, {self.datasets[owner]}
            )
            for selected in ("owner", "other_admin"):
                for suffix in ("accounts", "report", "report&export=csv", "export", "connections"):
                    action, _, extra = suffix.partition("&")
                    path = (
                        "/operator/v1/integration/"
                        + action
                        + "?dataset_id="
                        + self.datasets[selected]
                    )
                    if extra:
                        path += "&" + extra
                    allowed = selected == owner and (action != "connections" or role == "owner")
                    wanted = 200 if allowed else 404
                    if action == "connections" and role == "other_admin" and selected == owner:
                        wanted = 403
                    with self.subTest(role=role, dataset=selected, action=suffix):
                        before = self.footprint()
                        status, headers, raw = self.exchange("GET", path)
                        self.assertEqual(status, wanted, raw[:250])
                        self.assertNotIn(SECRET.encode(), raw)
                        self.assertEqual(self.footprint(), before)
                        if wanted == 200 and action in {"accounts", "report", "export"}:
                            self.assertIn(self.datasets[selected].encode(), raw)
                        if wanted == 200 and extra:
                            self.assertIn("attachment", headers["Content-Disposition"])
                            rows = list(csv.DictReader(io.StringIO(raw.decode())))
                            self.assertTrue(rows)
                            self.assertTrue(
                                all(row["dataset_id"] == self.datasets[selected] for row in rows)
                            )

    def test_binding_and_account_ids_cannot_be_rebound_to_another_dataset(self):
        self.cookie, self.csrf = self.identities["owner"]
        for row in POLICY["cases"]:
            if row["case"] not in {
                "account_state",
                "account_permissions",
                "credential_save",
                "credential_refresh",
                "credential_replace",
                "credential_disable",
                "credential_retire",
            }:
                continue
            with self.subTest(action=row["case"]):
                path, body = self.request_for(row)
                body["dataset_id"] = self.datasets["other_admin"]
                before = self.footprint()
                self.assert_reply(row, self.exchange("POST", path, body=body), 404)
                self.assertEqual(self.footprint(), before)
        # Even two datasets belonging to the same owner cannot exchange credential IDs.
        dataset = {**self.dataset_bodies["owner"], "dataset_id": "dataset.resource.sibling"}
        self.registry.integration.create_dataset(
            self.registry.principal("owner.local"), dataset, "3"
        )
        row = next(row for row in POLICY["cases"] if row["case"] == "credential_refresh")
        path, body = self.request_for(row)
        body["dataset_id"] = dataset["dataset_id"]
        before = self.footprint()
        self.assert_reply(row, self.exchange("POST", path, body=body), 409)
        self.assertEqual(self.footprint(), before)

    def test_current_owner_membership_is_rechecked_for_an_existing_reader_session(self):
        self.cookie, self.csrf = self.identities["readonly"]
        path = "/operator/v1/integration/report?dataset_id="
        self.assertEqual(self.exchange("GET", path + self.datasets["owner"])[0], 200)
        reader = self.principals["readonly"]
        self.change(
            "edit_principal",
            reader,
            {"display_name": "Moved reader", "owner": self.principals["other_admin"]},
        )
        before = self.footprint()
        self.assertEqual(self.exchange("GET", path + self.datasets["owner"])[0], 404)
        self.assertEqual(self.exchange("GET", path + self.datasets["other_admin"])[0], 200)
        self.assertEqual(self.footprint(), before)

    def test_model_and_principal_views_filter_current_grants_and_admin_metadata(self):
        self.cookie, self.csrf = self.identities["ordinary"]

        def view(path):
            status, _, raw = self.exchange("GET", "/operator/v1/" + path)
            self.assertEqual(status, 200, raw[:250])
            return json.loads(raw)

        self.assertEqual(
            {row["configuration_ref"] for row in view("models")["items"]}, {"cfg.demo"}
        )
        own = self.principals["ordinary"]
        self.assertEqual({row["principal_id"] for row in view("principals")["items"]}, {own})
        for path in ("models/cfg.demo", "principals/" + own):
            self.assertEqual(view(path)["history"], [])
        self.assertEqual(view("models/cfg.demo")["grants"], [])
        grant = self.registry.grants(principal_id=own)[0]
        self.change(
            "set_grant",
            own,
            {
                "configuration_ref": "cfg.demo",
                "status": "removed",
                "purposes": ["execution"],
                "task_classes": ["class.demo"],
            },
            grant["revision"],
        )
        before = self.footprint()
        self.assertEqual(view("models")["items"], [])
        self.assertEqual(self.exchange("GET", "/operator/v1/models/cfg.demo")[0], 404)
        self.assertEqual(self.exchange("GET", "/operator/v1/principals/owner.local")[0], 404)
        self.assertEqual(self.footprint(), before)

    def test_activity_detail_and_selectors_never_expand_an_ordinary_users_scope(self):
        self.cookie, self.csrf = self.identities["ordinary"]
        own = self.principals["ordinary"]
        for suffix in ("activity", "activity?principal_id=" + own):
            status, _, raw = self.exchange("GET", "/operator/v1/" + suffix)
            self.assertEqual(status, 200)
            self.assertEqual(
                [row["submission_id"] for row in json.loads(raw)["items"]],
                ["submission.resource.ordinary"],
            )
        for suffix in (
            "activity?principal_id=owner.local",
            "usage?principal_id=owner.local",
            "activity/submission.resource.owner",
            "access/explain?principal_id=owner.local&configuration_ref=cfg.demo&purpose=execution&task_class=class.demo",
        ):
            before = self.footprint()
            self.assertEqual(self.exchange("GET", "/operator/v1/" + suffix)[0], 404)
            self.assertEqual(self.footprint(), before)

    def test_revoked_browser_authority_cannot_reach_existing_mutation_targets(self):
        self.cookie, self.csrf = self.identities["other_admin"]
        user = self.users.get("owner.local", self.principals["other_admin"])
        self.update(user, status="suspended")
        for row in POLICY["cases"]:
            if row["method"] == "GET":
                continue
            path, body = self.request_for(row)
            before = self.footprint()
            self.assert_reply(row, self.exchange(row["method"], path, body=body), 401)
            self.assertEqual(self.footprint(), before)
        user = self.users.get("owner.local", self.principals["other_admin"])
        self.update(user, status="active")
        self.assertEqual(self.exchange("GET", "/operator/v1/session")[0], 401)

    def test_extra_family_segments_cannot_alias_records_or_launch_work(self):
        self.cookie, self.csrf = self.identities["owner"]
        for method, path, body in (
            ("GET", "/operator/v1/provider-validations/", None),
            ("GET", "/operator/v1/provider-validations/extra/op.resource.validation", None),
            ("POST", "/operator/v1/demos/extra/text", {"operation_id": "op.resource.malformed"}),
        ):
            with self.subTest(method=method, path=path):
                before = self.footprint()
                status, _, raw = self.exchange(method, path, body=body)
                self.assertEqual(status, 404, raw[:250])
                self.assertEqual(self.footprint(), before)


PASSWORD_CANARY = "Resource target replacement passphrase"
