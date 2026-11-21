"""Freeze existing source-size debt and reject new oversized definitions."""

import json
import unittest

from tools.source_size import ROOT, measure, oversized, regressions, repository_sizes


class SourceSizeTests(unittest.TestCase):
    def test_repository_stays_within_reviewed_ceilings(self):
        budget = json.loads((ROOT / "tools/source_size_budget.json").read_text())
        self.assertEqual(regressions(budget["ceilings"], repository_sizes()), [])

    def test_existing_growth_and_new_oversized_symbols_fail(self):
        key = "server/src/example.py:function:run"
        self.assertEqual(regressions({key: 120}, {key: 120}), [])
        self.assertIn("exceeds ceiling 120", regressions({key: 120}, {key: 121})[0])
        self.assertIn("exceeds ceiling 100", regressions({}, {key: 101})[0])

    def test_reductions_require_lowering_or_removing_allowances(self):
        key = "server/src/example.py:function:run"
        self.assertIn("lower ceiling", regressions({key: 120}, {key: 110})[0])
        self.assertIn("remove resolved", regressions({key: 120}, {key: 100})[0])
        self.assertIn("remove resolved", regressions({key: 120}, {})[0])
        self.assertEqual(regressions({}, {key: 100}), [])

    def test_nested_and_async_symbols_have_stable_qualified_names(self):
        sizes = measure(
            "server/src/example.py",
            "class Service:\n    async def run(self):\n        def action():\n            pass\n        return action()\n",
        )
        self.assertEqual(sizes["server/src/example.py:class:Service"], 5)
        self.assertEqual(sizes["server/src/example.py:function:Service.run"], 4)
        self.assertEqual(sizes["server/src/example.py:function:Service.run.action"], 2)

    def test_limits_cover_classes_and_nonpython_source_files(self):
        self.assertEqual(
            oversized({"server/src/example.py:class:Service": 601}),
            {"server/src/example.py:class:Service": 601},
        )
        self.assertEqual(oversized({"tests/example.cjs:file": 1500}), {})
        self.assertEqual(
            oversized({"tests/example.cjs:file": 1501}), {"tests/example.cjs:file": 1501}
        )
        self.assertEqual(
            measure("tools/example.cjs", "const value = 1;\n"), {"tools/example.cjs:file": 1}
        )
