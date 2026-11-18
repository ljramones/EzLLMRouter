"""Independent fixture arithmetic and DEV-09 team-overlay conservation checks."""
from decimal import Decimal
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
from duranki_server.demo_workspace import project_demo
from duranki_server.demo_workspace_team import project_team_demo

LEGACY = ROOT / "web/dev09_demo_fixture.json"
TEAM = ROOT / "web/dev09_team_demo_fixture.json"


def usd(total):
    return Decimal(total["known_subtotals"].get("USD", "0"))


class TeamDemoTests(unittest.TestCase):
    def test_independent_raw_token_rate_arithmetic_and_roster(self):
        old, new = json.loads(LEGACY.read_text()), json.loads(TEAM.read_text())
        self.assertEqual(old["identity"], "dev09-scripted-cost-demo-v1")
        self.assertEqual(new["identity"], "dev09-team-scripted-cost-demo-v2")
        rates = old["rates"]
        expected = {"main": ".32", "maya_direct": ".02", "vega_scheduled": ".08",
            "maya_patton": ".04", "oren_opportunity": ".39", "brant_prototype": ".27",
            "andrew_delivery": ".15", "andrew_direct": ".02", "scheduled_intelligence": ".10"}
        sums, ids = {}, set()
        for attempt in old["attempts"] + new["attempts"]:
            self.assertNotIn(attempt["id"], ids)
            ids.add(attempt["id"])
            rate = rates[attempt["provider"]]
            raw = (Decimal(attempt["input"]) * Decimal(rate["input_per_1000_usd"]) +
                   Decimal(attempt["output"]) * Decimal(rate["output_per_1000_usd"])) / Decimal(1000)
            self.assertEqual(raw, raw.quantize(Decimal("0.01")), attempt["id"])
            sums[attempt["story"]] = sums.get(attempt["story"], Decimal(0)) + raw
        self.assertEqual(sums, {story: Decimal(amount) for story, amount in expected.items()})
        self.assertEqual((sum((sums[x] for x in ("main", "maya_direct", "vega_scheduled", "maya_patton")),
                              Decimal(0)), sum(sums.values())), (Decimal(".46"), Decimal("1.39")))
        categories = {item["name"]: item["category"] for item in new["actors"]+new["actor_overrides"]
                      if "category" in item}
        self.assertEqual(categories, {"Vega": "Research", "Patton": "Operations", "Newton": "Scientific",
            "Relay": "Communications", "Ironside": "Production", "Boole": "Factory",
            "Turing": "IDE", "Cristi": "Corpus", "Orion": "Intelligence",
            "Bud": "Multi-Agent", "The Agency": "Agency"})
        self.assertEqual({item["name"] for item in new["actors"] if item["kind"] == "scripted user"},
                         {"Oren Abel-Wood", "Brant Arsenault", "Andrew Woods"})
        self.assertEqual(new["actor_overrides"][0]["name"], "Larry Mitchell")
        participating = {item["actor"] for item in new["events"] + new["attempts"]}
        self.assertTrue({item["id"] for item in new["actors"] + new["actor_overrides"]
                         if item.get("category")}.issubset(participating))
        self.assertTrue({"demo.user.oren", "demo.user.brant", "demo.user.andrew"}.issubset(participating))
        oren = {item["id"]: item for item in new["attempts"] if item["story"] == "oren_opportunity"}
        self.assertLess(oren["demo.attempt.oren.orion.research"]["start"],
                        oren["demo.attempt.oren.vega.research"]["at"])
        self.assertGreater(oren["demo.attempt.oren.newton.review"]["start"],
                           max(oren[key]["at"] for key in (
                               "demo.attempt.oren.vega.research", "demo.attempt.oren.orion.research",
                               "demo.attempt.oren.cristi.lookup")))

    def test_team_cutoffs_simultaneous_observation_and_lineage(self):
        report = project_team_demo(LEGACY, collection="team", story="team")
        self.assertEqual((usd(report["all_total"]), report["all_total"]["attempts"]), (Decimal("1.25"), 30))
        self.assertEqual((usd(report["legacy_total"]), usd(report["expanded_total"])),
                         (Decimal(".46"), Decimal("1.39")))
        points = {item["at"]: item for item in report["snapshots"]}
        self.assertEqual((usd(points[0]["total"]), points[0]["total"]["attempts"]), (Decimal(0), 0))
        self.assertEqual((usd(points[63]["total"]), usd(points[65]["total"])),
                         (Decimal(".74"), Decimal(".84")))
        self.assertEqual({item["id"] for item in report["attempts"] if item["usage_at"] == 65},
            {"demo.attempt.brant.boole.check", "demo.attempt.andrew.ironside.summary",
             "demo.attempt.andrew.direct"})
        self.assertEqual(usd(points[66]["total"]), Decimal(".84"))
        self.assertEqual(len(points[0]["outcomes"]), 0)
        self.assertEqual(len(report["snapshots"][-1]["outcomes"]), 6)
        root = next(item for item in report["snapshots"][-1]["workflows"]
                    if item["run_id"] == "demo.run.oren.agency")
        self.assertEqual((usd(root["direct"]), usd(root["delegated"]), usd(root["inclusive"])),
                         (Decimal(0), Decimal(".39"), Decimal(".39")))
        self.assertFalse(any(item["actor"] == "demo.agent.agency" for item in report["attempts"]))
        self.assertTrue(any(a["start"] < b["at"] and b["start"] < a["at"]
            for a in report["attempts"] for b in report["attempts"]
            if a["id"] == "demo.attempt.oren.vega.research" and b["id"] == "demo.attempt.oren.orion.research"))

    def test_shared_agent_direct_human_scheduled_and_filters(self):
        full = project_team_demo(LEGACY, collection="expanded", story="expanded_all")
        self.assertEqual((usd(full["all_total"]), full["all_total"]["attempts"]), (Decimal("1.39"), 33))
        by_user = {row["id"]: usd(row) for row in full["snapshots"][-1]["user"]}
        self.assertEqual(by_user, {"demo.user.larry": Decimal(".32"),
            "demo.user.maya": Decimal(".06"), "demo.user.oren": Decimal(".39"),
            "demo.user.brant": Decimal(".27"), "demo.user.andrew": Decimal(".17"),
            "__unknown__": Decimal(".18")})
        self.assertEqual(sum(by_user.values()), Decimal("1.39"))
        brant = project_team_demo(LEGACY, collection="team", story="team",
            person="demo.user.brant", actor="demo.agent.patton")["snapshots"][-1]
        andrew = project_team_demo(LEGACY, collection="team", story="team",
            person="demo.user.andrew", actor="demo.agent.patton")["snapshots"][-1]
        self.assertEqual((usd(brant["total"]), usd(andrew["total"])),
                         (Decimal(".05"), Decimal(".04")))
        self.assertEqual({item["root_run_id"] for item in brant["attempts"]}, {"demo.run.brant.patton"})
        self.assertEqual({item["root_run_id"] for item in andrew["attempts"]}, {"demo.run.andrew.patton"})
        direct = project_team_demo(LEGACY, story="andrew_direct")["snapshots"][-1]["attempts"]
        self.assertEqual((direct[0]["agent_id"], direct[0]["user"]), (None, "demo.user.andrew"))
        scheduled = project_team_demo(LEGACY, story="scheduled_intelligence")["snapshots"][-1]["attempts"]
        self.assertTrue(all(item["user"] is None and item["owner"] == "demo.team.mach33" for item in scheduled))
        self.assertEqual(usd(project_team_demo(LEGACY, story="team", provider="demo.provider.beacon")
                             ["snapshots"][-1]["total"]), Decimal(".61"))
        self.assertEqual(usd(project_team_demo(LEGACY, story="team", actor="demo.agent.agency")
                             ["snapshots"][-1]["total"]), Decimal(0))
        self.assertEqual(usd(project_demo(LEGACY, story="all")["snapshots"][-1]["total"]), Decimal(".46"))


if __name__ == "__main__":
    unittest.main()
