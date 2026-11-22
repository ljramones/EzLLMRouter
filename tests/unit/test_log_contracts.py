"""Route, level, schema and canary contracts are independent of log implementation."""

from datetime import datetime
import json
import logging
import runpy
from pathlib import Path
import subprocess
import sys
import unittest

from ezllmrouter_server import observability as logs
from tests.operator_console.test_authorization_matrix import policy_routes
from tests.operator_resource_fixtures import POLICY as RESOURCES
from tests.wire_authorization_policy import routes

CANARY = "private-payload-canary"
ACCESS_KEYS = {"at", "level", "event", "method", "route", "status", "elapsed_ms", "correlation_id"}


def labels():
    for method, registered, *_ in policy_routes():
        family = registered.endswith("*")
        path = registered.rstrip("*") + (CANARY if family else "")
        label = registered.rstrip("*/") + "/:id" if family else registered
        yield method, path, label
    for row in routes():
        path = row["path"]
        values = {
            key: "models"
            for key in (
                "submission",
                "task",
                "step",
                "revision",
                "generation",
                "run",
                "outcome",
                "account",
                "event",
                "snapshot",
                "credential_account",
            )
        }
        values["version"] = row["version"]
        import re

        expected = re.sub(r"\{(?!version\})[^}]+\}", ":id", path).format(version=row["version"])
        yield row["method"], path.format(**values), expected


class LogContractTests(unittest.TestCase):
    def access(self, method, path, status=200):
        with self.assertLogs("ezllmrouter", "INFO") as captured:
            logs.log_http_request(method, path, status, 7, "request.synthetic")
        self.assertEqual(len(captured.records), 1)
        return json.loads(logs.EventFormatter().format(captured.records[0]))

    def test_all_operator_and_wire_bindings_have_safe_labels_and_an_exact_access_schema(self):
        cases = list(labels())
        self.assertEqual(len(cases), 108)
        for method, path, expected in cases:
            for status in (200, 400, 401, 403, 404, 409, 426, 429, 503):
                with self.subTest(method=method, path=path, status=status):
                    entry = self.access(method, path + "?token=" + CANARY, status)
                    self.assertEqual(set(entry), ACCESS_KEYS)
                    self.assertEqual(entry["route"], expected)
                    self.assertEqual(
                        (entry["event"], entry["level"], entry["status"]),
                        ("http_request", "INFO", status),
                    )
                    self.assertIsNotNone(datetime.fromisoformat(entry["at"]).tzinfo)
                    self.assertEqual(entry["elapsed_ms"], 7)
                    self.assertNotIn(CANARY, json.dumps(entry))

    def test_dynamic_ids_are_redacted_even_when_they_equal_a_registered_route_word(self):
        for word in ("models", "password", "connections", "login", "report", "inventory", "save"):
            for prefix in (
                "/operator/v1/users/",
                "/operator/v1/models/",
                "/operator/v1/principals/",
                "/operator/v1/activity/",
                "/operator/v1/provider-validations/",
                "/v1/submissions/",
                "/v1/outcomes/",
            ):
                with self.subTest(word=word, prefix=prefix):
                    self.assertEqual(self.access("GET", prefix + word)["route"], prefix + ":id")
        for method in ("POST", "DELETE"):
            self.assertEqual(
                self.access(method, "/operator/v1/users/password")["route"],
                "/operator/v1/users/:id",
            )

    def test_family_actions_preserve_only_literal_operation_positions(self):
        for row in RESOURCES["cases"]:
            path = row["path"].split("?", 1)[0]
            values = {
                name: "login"
                for name in ("target", "connector", "dataset", "account", "binding", "ordinary")
            }
            label = path
            for name in values:
                label = label.replace("{" + name + "}", ":id")
            for dynamic in (
                "conn.resource",
                "op.resource.validation",
                "op.resource.launch",
                "cfg.demo",
                "cfg.resource.private",
                "owner.local",
                "submission.resource.ordinary",
                "submission.resource.owner",
            ):
                label = label.replace(dynamic, ":id")
            with self.subTest(case=row["case"]):
                self.assertEqual(self.access(row["method"], path.format(**values))["route"], label)

    def test_rejections_and_faults_have_distinct_levels_and_never_serialize_exception_values(self):
        for status, code in (
            (400, "SCHEMA_INVALID"),
            (401, "AUTHENTICATION_FAILED"),
            (403, "POLICY_DENIED"),
            (404, "NOT_FOUND_OR_FORBIDDEN"),
            (409, "PLAN_INVALID_OR_STALE"),
            (429, "LIMIT_EXCEEDED"),
            (503, "INTERNAL_UNAVAILABLE"),
        ):
            token = logs.REQUEST_CORRELATION.set("request.synthetic")
            try:
                with self.assertLogs("ezllmrouter", "INFO") as captured:
                    logs.log_rejection("wire.rejected", code=code, status=status)
                    try:
                        raise RuntimeError(CANARY)
                    except RuntimeError as error:
                        logs.log_failure("wire.failed", error, status=503)
            finally:
                logs.REQUEST_CORRELATION.reset(token)
            entries = [
                json.loads(logs.EventFormatter().format(record)) for record in captured.records
            ]
            self.assertEqual(
                set(entries[0]), {"at", "level", "event", "code", "status", "correlation_id"}
            )
            self.assertEqual((entries[0]["level"], entries[0]["status"]), ("INFO", status))
            self.assertEqual(
                set(entries[1]),
                {"at", "level", "event", "exception_type", "stack", "status", "correlation_id"},
            )
            self.assertEqual(entries[1]["level"], "ERROR")
            self.assertTrue(entries[1]["stack"])
            self.assertTrue(
                all(set(frame) == {"file", "function", "line"} for frame in entries[1]["stack"])
            )
            self.assertNotIn(CANARY, json.dumps(entries))

    def test_formatter_ignores_payload_headers_locals_and_arbitrary_log_arguments(self):
        record = logging.LogRecord(
            "ezllmrouter", logging.ERROR, __file__, 1, CANARY, (CANARY,), None
        )
        record.event = "controlled.failure"
        for key in ("headers", "body", "payload", "prompt", "response", "credential", "locals"):
            setattr(record, key, CANARY)
        entry = json.loads(logs.EventFormatter().format(record))
        self.assertEqual(set(entry), {"at", "level", "event"})
        self.assertNotIn(CANARY, json.dumps(entry))

    def test_unknown_paths_invalid_urls_and_method_words_never_become_literal_ids(self):
        self.assertEqual(logs._operator_tail("GET", "/operator/v1/users/", []), [])
        for method, path, expected in (
            ("GET", "/integration/v1/reports/models", "/integration/v1/reports/:id"),
            ("GET", "/v1/outcomes/models/password", "/v1/outcomes/:id/:id"),
            ("GET", "/integration/v1/credentials/bindings", "/integration/v1/credentials/bindings"),
            ("GET", "/integration/v1/reports/dataset", "/integration/v1/reports/dataset"),
            ("PATCH", "/operator/v1/users/models", "/operator/v1/:id/:id"),
            ("GET", "/operator/v1/users/", "/operator/v1/users"),
            ("GET", "/operator/v1/absent/models", "/operator/v1/:id/:id"),
            ("GET", "/v1/submissions/by-work", "/v1/submissions/:id"),
            ("GET", "/integration/v1/absent/models/secret", "/integration/v1/:id/:id/:id"),
            (
                "GET",
                "/integration/v1/credentials/models/not-an-action",
                "/integration/v1/credentials/:id/:id",
            ),
            (
                "POST",
                "/operator/v1/integration/absent/models/secret",
                "/operator/v1/integration/:id/:id/:id",
            ),
            ("GET", "http://[invalid", "/:id"),
            ("GET", "/unregistered/models", "/:id/:id"),
            ("GET", "/integration/v99/report", "/:id/:id/:id"),
            ("GET", "/v1/absent", "/:id/:id"),
            ("GET", "", "/"),
        ):
            with self.subTest(method=method, path=path):
                self.assertEqual(self.access(method, path)["route"], expected)
        self.assertEqual(
            self.access("GET", "/".join(["", "v1", "submissions"] + [CANARY] * 100))["route"].count(
                ":id"
            ),
            8,
        )
        self.assertEqual(self.access(CANARY, "/" + CANARY)["method"], "OTHER")

    def test_the_copied_worker_logger_needs_no_trusted_server_imports(self):
        path = str(Path(logs.__file__).resolve())
        copied = runpy.run_path(path)
        self.assertEqual(
            copied["safe_route"]("GET", "/operator/v1/users/models"), "/operator/v1/:id/:id"
        )
        source = (
            "import runpy,sys; m=runpy.run_path("
            + repr(path)
            + "); assert m['safe_route']('GET','/operator/v1/users/models')=='/operator/v1/:id/:id'; assert 'ezllmrouter_server' not in sys.modules"
        )
        subprocess.run([sys.executable, "-I", "-S", "-c", source], check=True, timeout=5)
