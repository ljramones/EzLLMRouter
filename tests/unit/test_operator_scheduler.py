"""Scheduler outcomes use explicit ticks instead of incidental background timing."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

from ezllmrouter_server.operator_http.application import OperatorApplication


def connection(**changes):
    return {
        "connection_id": "connection.scheduler",
        "checks_scheduled": True,
        "status": "active",
        "revision": 1,
        "check_interval_seconds": 10,
        "scheduled_operation": "inventory",
        **changes,
    }


class OperatorSchedulerTests(unittest.TestCase):
    def run_schedule(self, rows, times, *, failure=False):
        application = OperatorApplication.__new__(OperatorApplication)
        registry = Mock(identity=SimpleNamespace(owner_id="owner.scheduler"))
        application.registry = registry
        registry.list_connections.side_effect = rows
        if failure:
            registry.probe_connection.side_effect = RuntimeError("synthetic probe failure")
        application.scheduler_stop = Mock()
        application.scheduler_stop.wait.side_effect = [False] * len(rows) + [True]
        with (
            patch("ezllmrouter_server.operator_http.application.time.monotonic", side_effect=times),
            patch("ezllmrouter_server.operator_http.application.log_failure") as failure_log,
            patch(
                "ezllmrouter_server.operator_http.application.uuid.uuid4",
                return_value=SimpleNamespace(hex="synthetic"),
            ),
        ):
            application.scheduled_checks()
        self.assertEqual(
            application.scheduler_stop.wait.call_args_list, [call(2)] * (len(rows) + 1)
        )
        return registry, failure_log

    def test_no_registry_returns_without_waiting(self):
        application = OperatorApplication.__new__(OperatorApplication)
        application.registry = None
        application.scheduler_stop = Mock()
        application.scheduled_checks()
        application.scheduler_stop.wait.assert_not_called()

    def test_already_stopped_scheduler_performs_no_registry_reads(self):
        registry, logged = self.run_schedule([], [])
        registry.list_connections.assert_not_called()
        registry.probe_connection.assert_not_called()
        logged.assert_not_called()

    def test_list_failure_logs_and_continues_to_the_next_tick(self):
        registry, logged = self.run_schedule([RuntimeError("synthetic list failure"), []], [])
        registry.probe_connection.assert_not_called()
        self.assertEqual(registry.list_connections.call_count, 2)
        logged.assert_called_once_with("operator_http.scheduler.list_connections.failed")

    def test_unscheduled_disabled_and_incomplete_checks_do_not_probe(self):
        registry, logged = self.run_schedule(
            [
                [
                    connection(checks_scheduled=False),
                    connection(status="disabled"),
                    connection(check_interval_seconds=None),
                    connection(scheduled_operation=None),
                ]
            ],
            [0, 0],
        )
        registry.probe_connection.assert_not_called()
        logged.assert_not_called()

    def test_first_interval_is_waited_and_exact_due_time_probes_once(self):
        registry, logged = self.run_schedule([[connection()]] * 3, [0, 5, 10])
        registry.probe_connection.assert_called_once_with(
            "owner.scheduler", "connection.scheduler", 1, "probe.scheduled.synthetic", "inventory"
        )
        logged.assert_not_called()

    def test_revision_or_operation_changes_restart_the_due_interval(self):
        for changes in ({"revision": 2}, {"scheduled_operation": "readiness"}):
            with self.subTest(changes=changes):
                updated = connection(**changes)
                registry, logged = self.run_schedule(
                    [[connection()], [updated], [updated], [updated]], [0, 10, 15, 20]
                )
                registry.probe_connection.assert_called_once_with(
                    "owner.scheduler",
                    "connection.scheduler",
                    updated["revision"],
                    "probe.scheduled.synthetic",
                    updated["scheduled_operation"],
                )
                logged.assert_not_called()

    def test_removed_connections_lose_their_old_due_time(self):
        registry, logged = self.run_schedule(
            [[connection()], [], [connection()], [connection()]], [0, 20, 30]
        )
        registry.probe_connection.assert_called_once()
        logged.assert_not_called()

    def test_probe_failures_log_once_and_do_not_skip_the_next_interval(self):
        registry, logged = self.run_schedule([[connection()]] * 4, [0, 10, 15, 20], failure=True)
        self.assertEqual(registry.probe_connection.call_count, 2)
        self.assertEqual(
            logged.call_args_list, [call("operator_http.scheduler.probe_connection.failed")] * 2
        )
