"""CompletionIdentityTests behaviour regressions."""

from __future__ import annotations

import unittest
from tests.gateway_integration.completion_preflight_support import CompletionPreflightFixture


class CompletionIdentityTests(CompletionPreflightFixture, unittest.TestCase):
    def test_browser_assets_and_capture_source_bind_mount_identity(self):
        from tests.gateway_integration import test_completion_preflight as _api

        web = self.root / "web" / "usage_costs_view.js"
        browser = self.root / "tests" / "operator_console" / "dev12_completion_browser.cjs"
        request = self.root / "tests" / "development_slice" / "request.json"
        scenarios = self.root / "tests" / "tool_cycle" / "scenarios.json"
        web.parent.mkdir(parents=True)
        browser.parent.mkdir(parents=True)
        request.parent.mkdir(parents=True)
        scenarios.parent.mkdir(parents=True)
        web.write_text("const view = 1;\n")
        browser.write_text("const capture = 1;\n")
        request.write_text('{"request":1}\n')
        scenarios.write_text('{"scenarios":1}\n')
        first = _api.mounted_source_identity(self.root)
        self.assertEqual(first["file_count"], 4)
        web.write_text("const view = 2;\n")
        self.assertNotEqual(_api.mounted_source_identity(self.root)["sha256"], first["sha256"])
        web.write_text("const view = 1;\n")
        browser.write_text("const capture = 2;\n")
        self.assertNotEqual(_api.mounted_source_identity(self.root)["sha256"], first["sha256"])
        browser.write_text("const capture = 1;\n")
        request.write_text('{"request":2}\n')
        self.assertNotEqual(_api.mounted_source_identity(self.root)["sha256"], first["sha256"])
        request.write_text('{"request":1}\n')
        scenarios.write_text('{"scenarios":2}\n')
        self.assertNotEqual(_api.mounted_source_identity(self.root)["sha256"], first["sha256"])
        scenarios.unlink()
        with self.assertRaises(FileNotFoundError):
            _api.mounted_source_identity(self.root)

    def test_unversioned_database_is_refused_without_adoption_or_mutation(self):
        from tests.gateway_integration import test_completion_preflight as _api
        from ezllmrouter_server.store import SQLiteStore

        path = self.root / "unversioned.sqlite"
        with _api.sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE submissions (record TEXT)")
            connection.execute("INSERT INTO submissions VALUES (?)", ('{"attempt":"retained"}',))
        before = path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "unversioned database"):
            SQLiteStore(path)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(_api.Path(str(path) + "-wal").exists())

    def test_browser_attestation_requires_exact_target_or_retained_port_forward(self):
        from tests.gateway_integration import test_completion_preflight as _api
        from tools.gateway.evidence.dev12_completion_operator_handlers import _browser_attestation

        screenshot = self.root / "screen.png"
        screenshot.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic test capture")
        script = _api.Path(_api.__file__).resolve()
        report = {
            "attempts": [{"attempt_id": "attempt.synthetic.1"}],
            "total": {"known_usd": "0.010000000"},
        }
        direct_url = "http://127.0.0.1:37771"
        runtime = _api.SimpleNamespace(
            root=self.root,
            operator_url=direct_url,
            plan={"source_tree": "c" * 40, "envelope": {"campaign_id": "campaign.synthetic.test"}},
        )
        census = {
            "submissions": 1,
            "usage_revisions": 1,
            "receiver_arrivals": 1,
            "attempt_count": 1,
            "possible_send_count": 1,
        }
        ledger = {
            **census,
            "files": {
                name: {"present": False, "bytes": 0, "sha256": None}
                for name in (
                    "receiver.jsonl",
                    "guard.jsonl",
                    "send-events.jsonl",
                    "receiver-receipts.jsonl",
                )
            },
        }
        payload = {
            "kind": "dev12_controlled_browser_observation_v1",
            "campaign_id": runtime.plan["envelope"]["campaign_id"],
            "source_tree": runtime.plan["source_tree"],
            "operator_url": direct_url,
            "browser_url": direct_url,
            "port_forward": None,
            "target_probe": {
                "build_fingerprint": "a" * 64,
                "report_attempt_ids_sha256": _api.sha256(b"attempt.synthetic.1").hexdigest(),
                "report_total": report["total"],
            },
            "capture_source": str(
                script.relative_to(_api.Path(_api.__file__).resolve().parents[2])
            ),
            "capture_source_sha256": _api.sha256(script.read_bytes()).hexdigest(),
            "screenshots": [
                {"path": "screen.png", "sha256": _api.sha256(screenshot.read_bytes()).hexdigest()}
            ],
            "browser": {},
            "ledger_before": ledger,
            "ledger_after": ledger,
            "local_get_count": 2,
        }
        attestation = self.root / "operator-browser-evidence.json"
        with (
            _api.patch(
                "tools.gateway.evidence.dev12_completion_preflight.mounted_source_identity",
                return_value={"sha256": "a" * 64},
            ),
            _api.patch(
                "tools.gateway.evidence.dev12_completion_operator_handlers._census",
                return_value=census,
            ),
        ):
            attestation.write_text(_api.json.dumps(payload))
            self.assertEqual(_browser_attestation(runtime, attestation.name, report)[0], payload)
            payload["browser_url"] = "http://127.0.0.1:37772"
            attestation.write_text(_api.json.dumps(payload))
            with self.assertRaisesRegex(AssertionError, "port-forward"):
                _browser_attestation(runtime, attestation.name, report)
            mapping = self.root / "local-forward.json"
            mapping.write_text('{"from":"37771","to":"37772"}\n')
            payload["port_forward"] = {
                "from": direct_url,
                "to": payload["browser_url"],
                "method": "local_port_forward",
                "evidence_path": mapping.name,
                "sha256": _api.sha256(mapping.read_bytes()).hexdigest(),
            }
            attestation.write_text(_api.json.dumps(payload))
            self.assertEqual(_browser_attestation(runtime, attestation.name, report)[0], payload)
            mapping.write_text('{"from":"wrong"}\n')
            with self.assertRaisesRegex(AssertionError, "mapping evidence"):
                _browser_attestation(runtime, attestation.name, report)
