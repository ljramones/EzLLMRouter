"""Cycle validation must work for either iteration order of the affected set."""

import unittest
from unittest.mock import Mock, patch

from ezllmrouter_server import accounting_lineage as lineage
from ezllmrouter_server.integration_accounting import IntegrationError


class OrderedAffected(set):
    """A real set with one explicit legal iteration order, independent of hash seeds."""

    def __init__(self, order):
        super().__init__(order)
        self.order = tuple(order)

    def __iter__(self):
        return iter(self.order)


class LineageTraversalTests(unittest.TestCase):
    def check_graph(self, order, *, cycle=False):
        parent, child = "attempt.parent", "attempt.child"
        starts = {
            name: {
                "integration_version": "2",
                "attempt_role": "unknown",
                "logical_operation_id": "logical.synthetic",
                "task_id": "task.synthetic",
            }
            for name in (parent, child)
        }
        links = {
            parent: (
                "fallback" if cycle else "initial",
                child if cycle else None,
                "logical.synthetic",
            ),
            child: ("fallback", parent, "logical.synthetic"),
        }
        for name, (role, predecessor, _) in links.items():
            starts[name].update(
                attempt_id=name, attempt_role=role, predecessor_attempt_id=predecessor
            )
        database = Mock()
        component = ("dataset.synthetic", child, starts, {}, links)
        with (
            patch.object(lineage, "_lineage_component", return_value=component),
            patch.object(lineage, "_affected_attempts", return_value=OrderedAffected(order)),
        ):
            result = lineage._check_lineage(None, database, {})
        database.execute.assert_not_called()
        return result

    def test_cached_ancestor_and_complete_walk_accept_both_acyclic_orders(self):
        # Parent-first reaches an already checked ancestor after following an edge.
        # Child-first visits the whole chain, then skips an already checked start.
        for order in (("attempt.parent", "attempt.child"), ("attempt.child", "attempt.parent")):
            with self.subTest(order=order):
                self.assertIsNone(self.check_graph(order))

    def test_cycle_is_rejected_in_both_orders(self):
        for order in (("attempt.parent", "attempt.child"), ("attempt.child", "attempt.parent")):
            with self.subTest(order=order):
                with self.assertRaisesRegex(IntegrationError, "SEMANTIC_INVALID"):
                    self.check_graph(order, cycle=True)
