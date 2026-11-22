"""Real subprocess probes distinguish mutation outcomes and preserve source bytes."""

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.mutation_check import ROOT, run


class MutationRunnerTests(unittest.TestCase):
    def test_declared_critical_census_is_source_pinned_and_registered(self):
        from tools.check import MODULES, LOOPBACK_MODULES

        policy = json.loads((ROOT / "tests/fixtures/mutations/critical.json").read_text())
        self.assertEqual(
            {row["id"] for row in policy["mutations"]},
            {
                "removed-grant",
                "replayed-operation-payload",
                "published-price-identity",
                "early-backoff",
                "abandoned-first-write",
                "queue-capacity",
                "route-id-redaction",
            },
        )
        self.assertEqual(len(policy["mutations"]), 7)
        for row in policy["mutations"]:
            source = (ROOT / row["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(source).hexdigest(), row["source_sha256"])
            self.assertEqual(source.count(row["before"].encode()), 1)
            self.assertTrue(
                any(
                    row["selector"] == selector or row["selector"].startswith(selector + ".")
                    for selector in MODULES + LOOPBACK_MODULES
                )
            )

    def fixture(self, root):
        files = {
            "server/src/ezllmrouter_server/__init__.py": "",
            "server/src/ezllmrouter_server/decision.py": "def permitted(count):\n    return count > 0\n",
            "tests/__init__.py": "",
            "tests/case.py": "import unittest\nfrom ezllmrouter_server.decision import permitted\nclass Case(unittest.TestCase):\n    def test_positive(self):\n        self.assertTrue(permitted(1))\n",
            "tools/__init__.py": "",
            "tools/mutation_probe.py": (ROOT / "tools/mutation_probe.py").read_text(),
        }
        for name, value in files.items():
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(value)
        subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
        source = "server/src/ezllmrouter_server/decision.py"
        common = {
            "path": source,
            "source_sha256": hashlib.sha256((root / source).read_bytes()).hexdigest(),
            "before": "return count > 0",
            "selector": "tests.case.Case",
        }
        return {
            "mutations": [
                {**common, "id": name, "after": code}
                for name, code in (
                    ("killed", "return count < 0"),
                    ("survived", "return count >= 0"),
                    ("invalid", "return count >"),
                    ("timeout", "while True: pass"),
                )
            ]
        }

    def test_real_killed_survived_invalid_and_timeout_results_are_never_combined(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = self.fixture(root)
            before = (root / policy["mutations"][0]["path"]).read_bytes()
            report = run(policy, root / "results", root=root, timeout=2)
            self.assertFalse(report["passed"])
            self.assertEqual(
                report["counts"], {"killed": 1, "survived": 1, "invalid": 1, "timeout": 1}
            )
            self.assertTrue(all(row["baseline"]["passed"] for row in report["mutations"]))
            self.assertEqual((root / policy["mutations"][0]["path"]).read_bytes(), before)
            self.assertFalse(list((root / "results").glob("*/source-*")))
            self.assertFalse(list((root / "results").glob("*/*-tmp")))

    def test_stale_source_and_escaping_ids_fail_without_running_a_mutant(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = self.fixture(root)
            policy["mutations"] = policy["mutations"][:1]
            policy["mutations"][0]["source_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "identity changed"):
                run(policy, root / "stale", root=root)
            self.assertFalse(json.loads((root / "stale/summary.json").read_text())["passed"])
            policy["mutations"][0]["id"] = "../escape"
            with self.assertRaisesRegex(ValueError, "invalid mutation identity"):
                run(policy, root / "escape", root=root)
