"""Negative fixtures for scanner scope, finding identity, locks and advisory pages."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from tools.security_dependencies import INPUTS, ROOT, inventory, query, findings
from tools.security_sast import scan, errors


class SecurityGateFollowupTests(unittest.TestCase):
    def root(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for name in INPUTS:
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, root / name)
        return root

    def test_worker_deploy_and_tools_bad_source_cannot_escape_sast(self):
        root = self.root()
        for scope in ("worker/ezllmrouter_worker", "deploy/local", "tools"):
            path = root / scope / "bad.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("eval(input())  # noqa: S307\n")
        findings = scan(root)
        self.assertEqual(
            {row["path"] for row in findings if row["code"] == "S307"},
            {"worker/ezllmrouter_worker/bad.py", "deploy/local/bad.py", "tools/bad.py"},
        )

    def test_rehashing_cannot_approve_a_different_sql_finding_at_the_same_count(self):
        root = self.root()
        path = root / "server/src/query.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('def checked(table):\n return f"SELECT record FROM {table}"\n')
        findings = scan(root)
        from tools.security_sast import finding_identity

        policy = {
            "exceptions": [
                {
                    "path": "server/src/query.py",
                    "code": "S608",
                    "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "reason": "Synthetic guarded selector for identity regression.",
                    "findings": [finding_identity(root, row) for row in findings],
                }
            ]
        }
        self.assertEqual(errors(root, findings, policy), [])
        path.write_text('def unsafe(user_input):\n return f"SELECT record FROM {user_input}"\n')
        policy["exceptions"][0]["source_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertTrue(errors(root, scan(root), policy))

    def test_nonregistry_packages_and_missing_artifact_hashes_are_rejected(self):
        for replacement in (
            'source = { git = "https://example.invalid/synthetic.git" }',
            'source = { path = "unreviewed" }',
        ):
            root = self.root()
            path = root / "uv.lock"
            path.write_text(
                path.read_text().replace(
                    'source = { registry = "https://pypi.org/simple" }', replacement, 1
                )
            )
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                inventory(root)
        root = self.root()
        path = root / "uv.lock"
        path.write_text(path.read_text().replace('hash = "sha256:', 'hash = "invalid:', 1))
        with self.assertRaises(ValueError):
            inventory(root)

    def test_missing_npm_integrity_cannot_pass_inventory(self):
        root = self.root()
        path = root / "tests/playwright/package-lock.json"
        data = json.loads(path.read_text())
        row = next(value for key, value in data["packages"].items() if key)
        row.pop("integrity")
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            inventory(root)

    def test_native_manifest_dependencies_are_inventoried(self):
        data = inventory()
        self.assertIn("crates.io", {row["ecosystem"] for row in data["packages"]})
        for name in (
            "clients/go/go.mod",
            "clients/java/pom.xml",
            "clients/rust/Cargo.toml",
            "clients/dotnet/EzLLMRouter.Client/EzLLMRouter.Client.csproj",
        ):
            self.assertIn(name, data["source_sha256"])

    def test_osv_follows_pages_before_marking_a_snapshot_complete(self):
        data = {
            "sha256": "synthetic",
            "packages": [{"ecosystem": "PyPI", "name": "synthetic", "version": "1"}],
        }
        calls = []

        def fetch(route, body=None):
            calls.append((route, deepcopy(body)))
            if route == "querybatch":
                return {"results": [{"next_page_token": "next-synthetic"}]}
            if route == "query":
                self.assertEqual(body["page_token"], "next-synthetic")
                return {"vulns": [{"id": "TEST-PAGED-01"}]}
            return {"id": "TEST-PAGED-01"}

        result = query(data, fetch)
        self.assertEqual(
            [row["id"] for row in result["results"][0].get("vulns", [])], ["TEST-PAGED-01"]
        )
        self.assertTrue(any(route == "query" for route, _ in calls))

    def test_repeated_or_invalid_osv_page_tokens_fail(self):
        data = {
            "sha256": "synthetic",
            "packages": [{"ecosystem": "PyPI", "name": "synthetic", "version": "1"}],
        }
        for token in ("repeat", [], 17):

            def fetch(route, body=None, token=token):
                return (
                    {"results": [{"next_page_token": token}]}
                    if route == "querybatch"
                    else {"next_page_token": token}
                )

            with self.subTest(token=type(token).__name__), self.assertRaises(ValueError):
                query(data, fetch)

    def test_snapshot_with_an_unconsumed_page_cannot_be_replayed_as_complete(self):
        data = {
            "sha256": "synthetic",
            "packages": [{"ecosystem": "PyPI", "name": "synthetic", "version": "1"}],
        }
        snapshot = query(data, lambda *_: {"results": [{}]})
        snapshot["results"][0]["pages"][0]["next_page_token"] = "missing-page"
        with self.assertRaises(ValueError):
            findings(data, snapshot)

    def test_changed_npm_manifest_and_misnamed_python_wheel_are_rejected(self):
        root = self.root()
        path = root / "tests/playwright/package.json"
        shutil.copy2(ROOT / "tests/playwright/package.json", path)
        data = json.loads(path.read_text())
        data["devDependencies"]["typescript"] = "0.0.1"
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            inventory(root)
        root = self.root()
        path = root / "uv.lock"
        path.write_text(
            path.read_text().replace(
                "anyio-4.16.0-py3-none-any.whl", "unrelated-4.16.0-py3-none-any.whl", 1
            )
        )
        with self.assertRaises(ValueError):
            inventory(root)
