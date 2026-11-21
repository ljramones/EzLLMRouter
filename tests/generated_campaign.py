"""Campaign commands with renewed synthetic campaigns and integer exposure accounting."""

from decimal import Decimal
import random

from ezllmrouter_server.canonical import ContractError
from tests.generated_checks import Divergence, equal, run_trace
from tests.operator_console import test_personal_campaign as support

BOUND, ALLOWANCE = 1538400, 12000000


def commands(seed, count):
    rng, result = random.Random(seed), []
    for epoch in range((count + 15) // 16):
        a, b, c, d = (f"generated.{epoch}.{i}" for i in range(4))
        # Four live admissions per epoch, including over-bound and unknown costs.
        block = [
            {"op": "renew"},
            {"op": "reserve", "id": a},
            {"op": "reconcile_missing"},
            {"op": "settle", "id": a, "cost": rng.choice((BOUND + 1, BOUND * 2, ALLOWANCE + 1))},
            {"op": "reconcile", "id": a, "cost": rng.randrange(BOUND + 1)},
            {"op": "resume"},
            {"op": "reserve", "id": b},
            {"op": "unknown", "id": b},
            {"op": "reserve", "id": b + ".denied"},
            {"op": "reconcile", "id": b, "cost": rng.randrange(BOUND + 1)},
            {"op": "resume"},
            {"op": "reserve", "id": c},
            {"op": "release", "id": c},
            {"op": "reserve", "id": d},
            {"op": "settle", "id": d, "cost": rng.randrange(BOUND + 1)},
        ]
        block.append(
            {
                "op": rng.choice(("settle", "reconcile", "release", "unknown")),
                "id": rng.choice((a, b, c, d)),
                "cost": rng.randrange(BOUND * 3),
            }
        )
        result.extend(block)
    return result[:count]


class Model:
    def __init__(self, fixture):
        self.f = fixture
        self.state, self.attempts, self.previous = "active", {}, -1
        self.renew()

    def renew(self):
        if self.previous >= 0:
            self.f.campaign.transition("owner.local", "closed")
        self.f.campaign.configure("owner.local", {**self.f.config, "max_requests": 100})
        self.f.campaign.transition("owner.local", "active")
        self.previous += 1
        self.state, self.attempts = "active", {}

    def totals(self):
        spent = sum(
            row["cost"]
            for row in self.attempts.values()
            if row["state"] in ("settled", "over_bound")
        )
        held = sum(
            BOUND for row in self.attempts.values() if row["state"] in ("reserved", "unknown")
        )
        return spent, held

    def reserve(self, suffix):
        spent, held = self.totals()
        permitted = (
            self.state == "active"
            and not held
            and len(self.attempts) < 100
            and spent + BOUND <= ALLOWANCE
        )
        record = {**self.f._record(suffix), "status_revision": 1}
        try:
            with self.f.registry.send_authority.gate:
                self.f.store.create(
                    record, reserve=lambda db, item: self.f.campaign.reserve(db, item, 20, 16)
                )
        except ContractError:
            equal("reserve acceptance", False, permitted)
            equal("rejected admission rollback", None, self.f.store.get(record["submission_id"]))
            equal("rejected work claim", None, self.f.store.work_owner(record["work_key"]))
        else:
            equal("reserve acceptance", True, permitted)
            self.attempts[suffix] = {"state": "reserved", "cost": 0}

    def step(self, command):
        op, suffix = command["op"], command.get("id")
        if op == "renew":
            self.renew()
        elif op == "reserve":
            self.reserve(suffix)
        elif op == "reconcile_missing":
            before = self.f.campaign.summary()
            equal(
                "missing usage reconciliation",
                0,
                self.f.campaign.reconcile_recorded_usage("owner.local"),
            )
            equal("missing usage retained exposure", before, self.f.campaign.summary())
        elif op == "resume":
            if (
                self.state == "paused"
                and not self.totals()[1]
                and not any(r["state"] == "over_bound" for r in self.attempts.values())
            ):
                self.f.campaign.transition("owner.local", "active")
                self.state = "active"
        elif suffix in self.attempts:
            self.change_attempt(command)
        self.check()

    def change_attempt(self, command):
        op, suffix, amount = command["op"], command["id"], command.get("cost", 0)
        row, aid = self.attempts[suffix], "attempt." + suffix
        cost = {
            "status": "calculated",
            "currency": "USD",
            "amount_decimal": f"{amount // 1000000000}.{amount % 1000000000:09d}",
        }
        if op == "reconcile":
            self.f.store.update("submission." + suffix, {}, usage={"attempt_id": aid, "cost": cost})
            self.f.campaign.reconcile_recorded_usage("owner.local")
            if row["state"] != "released":
                row.update(state="over_bound" if amount > BOUND else "settled", cost=amount)
                if amount > BOUND:
                    self.state = "paused"
            before = self.f.campaign.summary()
            equal(
                "reconciliation idempotency",
                0,
                self.f.campaign.reconcile_recorded_usage("owner.local"),
            )
            equal("reconciliation stable summary", before, self.f.campaign.summary())
        else:
            self.f.campaign.settle(
                aid, {"cost": cost} if op == "settle" else None, before_transmit=op == "release"
            )
            if row["state"] not in ("reserved", "unknown"):
                return
            if op == "release":
                if row["state"] == "reserved":
                    row["state"] = "released"
            elif op == "unknown":
                row["state"], self.state = "unknown", "paused"
            else:
                row.update(state="over_bound" if amount > BOUND else "settled", cost=amount)
                if amount > BOUND:
                    self.state = "paused"

    def check(self):
        summary, (spent, held) = self.f.campaign.summary(), self.totals()
        for key, expected in (
            ("incurred_decimal", spent),
            ("outstanding_decimal", held),
            ("available_decimal", max(0, ALLOWANCE - spent - held)),
        ):
            equal(key, expected, Decimal(summary[key]) * 1000000000)
        equal("campaign state", self.state, summary["state"])
        equal("request count", len(self.attempts), summary["request_count"])
        equal("previous campaigns", self.previous, summary["previous_campaigns"])
        equal(
            "attempt states",
            {"attempt." + key: value["state"] for key, value in self.attempts.items()},
            {row["attempt_id"]: row["state"] for row in summary["attempts"]},
        )


def execute(steps):
    fixture = support.CampaignTests("runTest")
    fixture.setUp()
    try:
        model = Model(fixture)
        for index, command in enumerate(steps):
            try:
                model.step(command)
            except Divergence as error:
                error.index = index
                raise
        fixture.campaign.transition("owner.local", "closed")
        before = fixture.campaign.summary()
        model.state = "closed"
        model.reserve("after-close")
        equal("closed exposure retained", before, fixture.campaign.summary())
    finally:
        fixture.doCleanups()


def run(seed, count):
    run_trace("campaign", seed, commands(seed, count), execute)
