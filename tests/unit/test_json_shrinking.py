"""Reducers preserve the failing invariant while simplifying JSON payloads."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.generated_checks import Divergence, reduce_trace, run_trace


class JSONShrinkingTests(unittest.TestCase):
    def test_nested_json_and_scalar_values_shrink_with_a_fixed_replay_budget(self):
        steps = [{"id": 99, "data": {"noise": [1, 2, 3], "trigger": 123456}}]
        calls = []

        def fails(candidate):
            calls.append(candidate)
            return any(
                type(row) is dict
                and type(row.get("data")) is dict
                and type(row["data"].get("trigger")) is int
                and row["data"]["trigger"] > 0
                for row in candidate
            )

        reduced = reduce_trace(steps, fails, budget=96)
        self.assertEqual(reduced, [{"data": {"trigger": 1}}])
        self.assertLessEqual(len(calls), 96)
        self.assertEqual(steps[0]["data"]["trigger"], 123456)
        self.assertEqual(reduced, reduce_trace(steps, fails, budget=96))

    def test_string_and_key_reduction_preserve_unicode_and_escaped_text(self):
        steps = [{"wide-unneeded-key": 10, "data": ["😀\nneedle\\tail", False, None]}]

        def fails(value):
            return any(
                type(row) is dict
                and any(type(item) is str and "needle" in item for item in row.get("data", []))
                for row in value
            )

        self.assertEqual(reduce_trace(steps, fails, budget=160), [{"data": ["needle"]}])

    def test_invalid_candidates_and_other_invariants_do_not_replace_the_first_failure(self):
        def execute(steps):
            for index, step in enumerate(steps):
                value = step["data"]["trigger"]
                if type(value) is not int:
                    raise TypeError("invalid generated command")
                if value == 0:
                    raise Divergence("other invariant", 1, value)
                if value > 0:
                    error = Divergence("first invariant", 0, value)
                    error.index = index
                    raise error

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict(os.environ, {"EZLLMROUTER_TEST_HEALTH": temporary}),
        ):
            with self.assertRaisesRegex(AssertionError, "minimized"):
                run_trace("json-shrink", 42, [{"data": {"trigger": 99}}], execute)
            trace = json.loads(
                next((Path(temporary) / "generated-failures").glob("*.json")).read_text()
            )
            self.assertEqual(trace["rule"], "first invariant")
            self.assertEqual(trace["minimized"], [{"data": {"trigger": 1}}])
            self.assertLessEqual(trace["reduction"]["attempts"], 48)
