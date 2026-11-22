"""Keep the declared shared matrix and limit-to-test inventory executable."""

import ast
import json
import inspect
from pathlib import Path
import re
import unittest

from tools.check import MODULES, LOOPBACK_MODULES
from ezllmrouter_server.execution_resources import BoundedExecutor

ROOT = Path(__file__).resolve().parents[2]
POLICIES = ROOT / "tests/fixtures/contracts/transport-security"


class TransportInventoryTests(unittest.TestCase):
    def test_every_documented_runtime_resource_has_registered_boundary_regressions(self):
        policy = json.loads((POLICIES / "limits.json").read_text())
        rows = policy["resources"]
        self.assertEqual(len(rows), 18)
        names = [row["resource"] for row in rows]
        self.assertEqual(len(set(names)), len(names))
        guide = (ROOT / "docs/RESOURCES.md").read_text().split("## Shutdown order")[0]
        documented = re.findall(r"^\| ([^|]+) \|", guide, re.MULTILINE)[2:]
        self.assertEqual(set(documented) - set(names), set())
        by_name = {row["resource"]: row["limits"] for row in rows}
        for resource, source in (
            ("Controlled execution", "server/src/ezllmrouter_server/core.py"),
            ("Successor execution", "tools/synthetic/successor_service.py"),
            ("Trusted sender checks", "server/src/ezllmrouter_server/gateway/guard.py"),
        ):
            tree = ast.parse((ROOT / source).read_text())
            calls = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "BoundedExecutor"
            ]
            self.assertEqual(len(calls), 1, source)
            options = {kw.arg: ast.literal_eval(kw.value) for kw in calls[0].keywords}
            self.assertEqual(options["max_workers"], by_name[resource]["workers"])
            self.assertEqual(
                options.get(
                    "max_pending",
                    inspect.signature(BoundedExecutor).parameters["max_pending"].default,
                ),
                by_name[resource]["capacity"],
            )
        for row in rows:
            self.assertTrue(row["limits"])
            self.assertTrue(row["tests"])
            for selector in row["tests"]:
                with self.subTest(resource=row["resource"], selector=selector):
                    module, cls, method = selector.rsplit(".", 2)
                    self.assertTrue(
                        any(
                            selector.startswith(registered + ".") or module == registered
                            for registered in MODULES + LOOPBACK_MODULES
                        )
                    )
                    tree = ast.parse((ROOT / (module.replace(".", "/") + ".py")).read_text())
                    owner = next(
                        node
                        for node in tree.body
                        if isinstance(node, ast.ClassDef) and node.name == cls
                    )
                    self.assertTrue(
                        any(
                            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and node.name == method
                            for node in owner.body
                        )
                    )

    def test_shared_transport_oracles_keep_their_case_and_client_census(self):
        matrix = json.loads((POLICIES / "resilience.json").read_text())
        self.assertEqual(
            matrix["clients"], ["python", "javascript", "go", "java", "dotnet", "rust"]
        )
        self.assertEqual(matrix["operation"], "GET /v1/capabilities")
        cases = matrix["cases"]
        self.assertEqual(len(cases), 28)
        self.assertEqual(len({row["id"] for row in cases}), 28)
        for case in cases:
            self.assertEqual(case["requests"], 0 if case["id"] == "untrusted_tls" else 1)
            self.assertIn(case["retry_guidance"], ("never", "query_first"))
        decoders = json.loads((POLICIES / "decoder_cases.json").read_text())
        self.assertEqual(len(decoders["cases"]), 536)
