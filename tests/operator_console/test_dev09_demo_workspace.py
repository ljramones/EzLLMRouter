"""Conservation and replay cutoffs for the fixed DEV-09 scripted workspace."""

from decimal import Decimal
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
from ezllmrouter_server.demo_workspace import project_demo


FIXTURE = ROOT / "web/dev09_demo_fixture.json"


def usd(total):
    return Decimal(total["known_subtotals"].get("USD", "0"))


def grouped(snapshot, key):
    return {row["id"]: usd(row) for row in snapshot[key]}


class DemoWorkspaceTests(unittest.TestCase):
    def test_main_completion_and_cumulative_steps(self):
        report = project_demo(FIXTURE)
        points = {row["at"]: usd(row["total"]) for row in report["snapshots"]}
        self.assertEqual(
            {second: points[second] for second in (0, 5, 20, 30, 45, 60, 70, 80, 90)},
            {
                0: Decimal("0"),
                5: Decimal(".03"),
                20: Decimal(".15"),
                30: Decimal(".19"),
                45: Decimal(".24"),
                60: Decimal(".30"),
                70: Decimal(".30"),
                80: Decimal(".32"),
                90: Decimal(".32"),
            },
        )
        done = report["snapshots"][-1]
        self.assertEqual(done["total"]["attempts"], 6)
        self.assertEqual(
            grouped(done, "actor"),
            {
                "demo.agent.patton": Decimal(".11"),
                "demo.agent.vega": Decimal(".17"),
                "demo.agent.newton": Decimal(".04"),
            },
        )
        root = next(row for row in done["workflows"] if row["run_id"] == "demo.run.main.patton")
        self.assertEqual(
            (usd(root["direct"]), usd(root["delegated"]), usd(root["inclusive"])),
            (Decimal(".11"), Decimal(".21"), Decimal(".32")),
        )
        self.assertEqual(grouped(done, "user"), {"demo.user.larry": Decimal(".32")})

    def test_all_stories_and_filters_reconcile(self):
        report = project_demo(FIXTURE, story="all")
        done = report["snapshots"][-1]
        self.assertEqual((usd(done["total"]), done["total"]["attempts"]), (Decimal(".46"), 9))
        self.assertEqual(
            [usd(row["total"]) for row in report["stories"]],
            [Decimal(".32"), Decimal(".02"), Decimal(".08"), Decimal(".04")],
        )
        self.assertEqual(
            grouped(done, "actor"),
            {
                "demo.agent.patton": Decimal(".15"),
                "demo.agent.vega": Decimal(".25"),
                "demo.agent.newton": Decimal(".04"),
                "demo.user.maya": Decimal(".02"),
            },
        )
        self.assertEqual(
            grouped(done, "provider"),
            {"demo.provider.arc": Decimal(".21"), "demo.provider.beacon": Decimal(".25")},
        )
        self.assertEqual(
            grouped(done, "user"),
            {
                "demo.user.larry": Decimal(".32"),
                "demo.user.maya": Decimal(".06"),
                "__unknown__": Decimal(".08"),
            },
        )
        self.assertEqual(grouped(done, "owner")["demo.team.mach33"], Decimal(".08"))
        self.assertEqual(
            sum((Decimal(item["amount_decimal"]) for item in done["attempts"]), Decimal(0)),
            usd(done["total"]),
        )
        filtered = project_demo(
            FIXTURE, story="all", actor="demo.agent.patton", provider="demo.provider.arc"
        )["snapshots"][-1]
        self.assertEqual(
            (filtered["total"]["attempts"], usd(filtered["total"])), (4, Decimal(".15"))
        )
        self.assertEqual(len({item["id"] for item in filtered["attempts"]}), 4)

    def test_reprojection_and_empty_coverage(self):
        first = project_demo(FIXTURE, actor="demo.agent.idle")
        second = project_demo(FIXTURE, actor="demo.agent.idle")
        self.assertEqual(first, second)
        self.assertEqual(first["snapshots"][-1]["total"]["attempts"], 0)
        self.assertEqual(
            {item["id"]: item["coverage"] for item in first["actors"]}["demo.agent.uninstrumented"],
            "Not measured",
        )
        with self.assertRaises(ValueError):
            project_demo(FIXTURE, actor="owner.local")


if __name__ == "__main__":
    unittest.main()
