"""Exercise the real security scanner on disposable bad source, without executing it."""

import hashlib
from pathlib import Path
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import shutil

from tools.security_sast import errors, scan, finding_identity
from tools.security_dependencies import INPUTS, ROOT, inventory, query, findings, sbom, fetch


class SecurityScanningTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "server/src").mkdir(parents=True)
        (self.root / "clients/python/src").mkdir(parents=True)

    def test_fake_hardcoded_password_and_eval_fail_even_with_noqa(self):
        (self.root / "server/src/bad.py").write_text(
            'password = "synthetic scanner canary"  # noqa: S105\neval(input())  # noqa: S307\n'
        )
        findings = scan(self.root)
        self.assertEqual({row["code"] for row in findings}, {"S105", "S307"})
        self.assertEqual(len(errors(self.root, findings, {"exceptions": []})), 2)

    def test_reviewed_sql_exception_fails_if_its_guard_changes_or_finding_disappears(self):
        path = self.root / "server/src/query.py"
        source = 'def query(table):\n    if table not in {"approved"}:\n        raise ValueError("table")\n    return f"SELECT record FROM {table}"\n'
        path.write_text(source)
        policy = {
            "exceptions": [
                {
                    "path": "server/src/query.py",
                    "code": "S608",
                    "count": 1,
                    "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "reason": "The table selector is allowlisted and data values use parameters.",
                }
            ]
        }
        findings = scan(self.root)
        policy["exceptions"][0]["findings"] = [finding_identity(self.root, row) for row in findings]
        self.assertEqual(errors(self.root, findings, policy), [])
        path.write_text(source.replace('table not in {"approved"}', "False"))
        policy["exceptions"][0]["source_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertTrue(
            errors(self.root, scan(self.root), policy), "rehashing cannot approve a disabled guard"
        )
        policy["exceptions"][0]["source_sha256"] = hashlib.sha256(source.encode()).hexdigest()
        path.write_text(
            source.replace(
                '    if table not in {"approved"}:\n        raise ValueError("table")\n', ""
            )
        )
        self.assertTrue(errors(self.root, scan(self.root), policy))
        path.write_text(source)
        self.assertTrue(errors(self.root, [], policy), "resolved exceptions must be removed")


class DependencyAuditTests(unittest.TestCase):
    def input_copy(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for name in INPUTS:
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, root / name)
        return root

    def test_equivalent_forbidden_release_spellings_cannot_bypass_the_inventory(self):
        root = self.input_copy()
        lock = root / "deploy/local/inputs/gateway/requirements.gateway.lock"
        original = lock.read_text()
        for version in (
            "1.107",
            "1.107.0.0",
            "1.107.0+local",
            "v1.107.0",
            "01.0107.000",
            "1.107.0.post1",
            "1.107.0rc1",
        ):
            with self.subTest(version=version):
                lock.write_text(original.replace("litellm==1.105.1", "litellm==" + version))
                with self.assertRaisesRegex(ValueError, "forbidden LiteLLM"):
                    inventory(root)
        lock.write_text(original)
        self.assertTrue(inventory(root)["packages"])

    def test_deployment_and_workflow_images_reject_mutable_or_forbidden_litellm(self):
        root = self.input_copy()
        digest = "@sha256:" + "a" * 64
        declarations = (
            ("deploy/nested/Dockerfile.synthetic", "FROM --platform=linux/arm64 {} AS worker\n"),
            ("deploy/compose.synthetic.yml", 'services:\n  worker:\n    image: "{}"\n'),
            (
                ".github/workflows/synthetic.yaml",
                'jobs:\n  check:\n    container: {{image: "{}"}}\n',
            ),
            (".github/workflows/synthetic.yaml", 'jobs:\n  check:\n    container: "{}"\n'),
        )
        for relative, template in declarations:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            for tag in (
                "latest",
                "main-latest",
                "main-stable",
                "v1.105.1",
                "latest" + digest,
                "v1.107.0" + digest,
                "1.107" + digest,
            ):
                with self.subTest(path=relative, tag=tag):
                    path.write_text(template.format("ghcr.io/berriai/litellm:" + tag))
                    with self.assertRaisesRegex(ValueError, "LiteLLM image"):
                        inventory(root)
            path.write_text(template.format("ghcr.io/berriai/litellm:v1.105.1" + digest))
            self.assertTrue(inventory(root)["packages"])
            path.unlink()

    def test_python_environment_jobs_scan_inputs_before_installing_project_dependencies(self):
        import re

        for workflow in ("check.yml", "testing-scheduled.yml"):
            source = (ROOT / ".github/workflows" / workflow).read_text()
            for block in re.split(r"(?m)^  (?=[a-zA-Z0-9_-]+:\s*$)", source):
                if "uv sync" in block:
                    with self.subTest(workflow=workflow, job=block.splitlines()[0]):
                        self.assertIn("python3 -I -S tools/security_dependencies.py", block)
                        self.assertLess(
                            block.index("python3 -I -S tools/security_dependencies.py"),
                            block.index("uv sync"),
                        )

    def test_image_syntax_cannot_hide_a_reference_or_misclassify_a_stage_alias(self):
        root = self.input_copy()
        path = root / "deploy/compose.synthetic.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        for source in (
            'services:\n  worker:\n    "image": "litellm:latest"\n',
            "services:\n  worker:\n    image: >-\n      litellm:latest\n",
            "services:\n  worker:\n    image: &unsafe litellm:latest\n",
            "services:\n  worker:\n    image: *unresolved\n",
        ):
            with self.subTest(source=source):
                path.write_text(source)
                with self.assertRaisesRegex(ValueError, "image"):
                    inventory(root)
        path.unlink()
        dockerfile = root / "deploy/Dockerfile.synthetic"
        dockerfile.write_text("FROM python@sha256:" + "b" * 64 + " AS litellm\n")
        self.assertTrue(inventory(root)["packages"])

    def test_inventory_distinguishes_shipped_and_development_libraries_and_emits_unique_components(
        self,
    ):
        data = inventory()
        versions = {row["version"] for row in data["packages"] if row["name"] == "anyio"}
        self.assertEqual(versions, {"4.15.1", "4.16.0"})
        self.assertEqual(set(data["source_sha256"]), set(INPUTS))
        self.assertIn("uv-build", {row["name"] for row in data["packages"]})
        components = sbom(data)["components"]
        self.assertEqual(len(components), len({row["bom-ref"] for row in components}))
        self.assertEqual(len(components), len(data["packages"]))

    def test_forbidden_litellm_and_unparsed_lock_records_fail_before_any_install_or_audit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in INPUTS:
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, root / name)
            lock = root / "deploy/local/inputs/gateway/requirements.gateway.lock"
            original = lock.read_text()
            lock.write_text(original.replace("litellm==1.105.1", "litellm==1.107.0"))
            with self.assertRaisesRegex(ValueError, "forbidden LiteLLM"):
                inventory(root)
            lock.write_text(original + "unresolved-package>=1\n")
            with self.assertRaisesRegex(ValueError, "unparsed frozen lock"):
                inventory(root)

    @staticmethod
    def affected(route, body=None):
        if route == "querybatch":
            return {
                "results": [
                    {"vulns": [{"id": "TEST-ADVISORY-01"}]}
                    if row["package"]["name"] == "litellm"
                    else {}
                    for row in body["queries"]
                ]
            }
        return {"id": "TEST-ADVISORY-01", "database_specific": {"severity": "HIGH"}}

    def test_known_affected_pin_blocks_and_stale_incomplete_or_changed_inventory_cannot_pass(self):
        data = inventory()
        snapshot = query(data, self.affected)
        issues = findings(data, snapshot)
        self.assertTrue(issues)
        self.assertTrue(all(row["blocking"] for row in issues))
        self.assertEqual({row["package"]["name"] for row in issues}, {"litellm"})
        for changed in (
            {"complete": False},
            {"inventory_sha256": "wrong"},
            {"results": []},
            {"queried_at": (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()},
            {"queried_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()},
        ):
            with self.subTest(changed=tuple(changed)), self.assertRaises(ValueError):
                findings(data, {**snapshot, **changed})
        with self.assertRaisesRegex(ValueError, "incomplete advisory batch"):
            query(data, lambda *_args: {"results": []})
        with self.assertRaises(OSError):
            query(data, lambda *_args: (_ for _ in ()).throw(OSError("offline synthetic outage")))

    def test_withdrawn_low_and_unrated_advisories_have_explicit_outcomes(self):
        data = inventory()
        snapshot = query(data, self.affected)
        identifier = "TEST-ADVISORY-01"
        snapshot["vulnerabilities"][identifier]["database_specific"]["severity"] = "LOW"
        self.assertTrue(all(not row["blocking"] for row in findings(data, snapshot)))
        snapshot["vulnerabilities"][identifier]["database_specific"] = {}
        self.assertTrue(all(row["blocking"] for row in findings(data, snapshot)))
        snapshot["vulnerabilities"][identifier]["withdrawn"] = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).isoformat()
        self.assertEqual(findings(data, snapshot), [])
        mismatched = deepcopy(snapshot)
        mismatched["vulnerabilities"][identifier]["id"] = "TEST-OTHER"
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            findings(data, mismatched)
        with self.assertRaisesRegex(ValueError, "invalid advisory route"):
            fetch("https://untrusted.test")
