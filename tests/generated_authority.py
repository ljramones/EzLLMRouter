"""Independent grant scopes, immutable price history and exact integer costing."""

from copy import deepcopy
from decimal import Decimal
import random

from ezllmrouter_server.canonical import ContractError
from ezllmrouter_server.core import usage_revision
from ezllmrouter_server.registry import RegistryConflict
from tests.generated_checks import Divergence, equal, run_trace
from tests.operator_console import test_registry as support


def commands(seed, count):
    rng = random.Random(seed)
    result = []
    for index in range(count):
        result.append(
            {
                "id": index,
                "action": ("grant", "price", "state")[index % 3],
                "model": rng.choice(("cfg.demo", "cfg.beta")),
                "principal": rng.choice(("svc.demo", "svc.beta")),
                "data": {
                    "status": rng.choice(("active", "removed")),
                    "purposes": rng.choice((["execution"], ["review"], ["execution", "execution"])),
                    "task_classes": rng.choice(
                        (["class.demo"], ["class.other"], ["class.demo", "class.other"])
                    ),
                    "rate": rng.randrange(1, 10000000),
                    "model_state": rng.choice(("enabled", "disabled")),
                },
            }
        )
    return result


def rejection(registry, request, snapshot):
    try:
        registry.mutate("owner.local", request)
    except (ValueError, RegistryConflict):
        pass
    else:
        raise Divergence("rejected mutation", "rejection", "accepted")
    equal("rejected write snapshot", snapshot, observe(registry))


def observe(registry):
    return {
        "version": registry.version(),
        "models": registry.list_models(),
        "grants": registry.grants(),
        "prices": {ref: registry.prices(ref) for ref in ("cfg.demo", "cfg.beta")},
    }


def nanos(value):
    return str(value // 1000000000) + "." + str(value % 1000000000).zfill(9)


def execute(steps):
    fixture = support.RegistryTests("runTest")
    fixture.setUp()
    try:
        fixture.model_b()
        fixture.principal()
        registry = fixture.registry
        models = {ref: deepcopy(registry.model(ref)) for ref in ("cfg.demo", "cfg.beta")}
        grants = {
            (row["principal_id"], row["configuration_ref"]): deepcopy(row)
            for row in registry.grants()
        }
        history = {ref: deepcopy(registry.prices(ref)) for ref in models}
        pinned = []
        for index, command in enumerate(steps):
            try:
                apply(registry, command, models, grants, history, pinned)
            except Divergence as error:
                error.index = index
                raise
    finally:
        fixture.doCleanups()


def apply(registry, command, models, grants, history, pinned):
    ref, principal, action, data = (
        command[key] for key in ("model", "principal", "action", "data")
    )
    model = models[ref]
    if action == "grant":
        old = grants.get((principal, ref))
        body = {
            "action": "set_grant",
            "subject": principal,
            "expected_revision": old["revision"] if old else 0,
            "data": {
                "configuration_ref": ref,
                **{key: data[key] for key in ("status", "purposes", "task_classes")},
            },
        }
    elif action == "price":
        # Integer nanodollar rates and whole-million token counts give an exact
        # integer oracle, independent of the runtime Decimal/rounding helpers.
        rate = data["rate"]
        body = {
            "action": "publish_price",
            "subject": ref,
            "expected_revision": model["revision"],
            "data": {
                "price_version": f"price.generated.{command['id']}",
                "currency": "USD",
                "rates": {"input_uncached": nanos(rate), "output_text": nanos(rate * 3)},
                "source": "synthetic fixture",
                "usage_semantics_version": "synthetic.text.v1",
            },
        }
    else:
        body = {
            "action": "model_state",
            "subject": ref,
            "expected_revision": model["revision"],
            "data": {"status": data["model_state"], "reason": "Synthetic state model"},
        }
    body["operation_id"] = f"op.authority-model.{command['id']}"
    before = observe(registry)
    if action == "grant" and data["status"] == "active" and model["status"] != "enabled":
        rejection(registry, body, before)
    else:
        reply = registry.mutate("owner.local", body)
        equal("accepted authority version", before["version"] + 1, registry.version())
        after = observe(registry)
        equal("exact operation replay", reply, registry.mutate("owner.local", deepcopy(body)))
        equal("replay has no side effects", after, observe(registry))
        if action == "grant":
            expected = {
                "revision": body["expected_revision"] + 1,
                "status": data["status"],
                "purposes": sorted(set(data["purposes"])),
                "task_classes": sorted(set(data["task_classes"])),
            }
            actual = registry.grant(principal, ref)
            for key, value in expected.items():
                equal("grant " + key, value, actual[key])
            grants[principal, ref] = actual
        else:
            model["revision"] += 1
            if action == "state":
                model["status"] = data["model_state"]
            else:
                model["price_version"] = body["data"]["price_version"]
                actual = registry.prices(ref)[-1]
                equal("published price version", model["price_version"], actual["price_version"])
                equal(
                    "exact input rate",
                    Decimal(nanos(data["rate"])),
                    Decimal(actual["rates"]["input_uncached"]),
                )
                equal(
                    "exact output rate",
                    Decimal(nanos(data["rate"] * 3)),
                    Decimal(actual["rates"]["output_text"]),
                )
                history[ref].append(actual)
                decision = {
                    "price_version": actual["price_version"],
                    "usage_semantics_version": "synthetic.text.v1",
                    "price_schedule": deepcopy(actual),
                }
                pinned.append((decision, data["rate"] * 7))
        equal("model revision", model["revision"], registry.model(ref)["revision"])
        actual_model = registry.model(ref)
        equal(
            "current model price",
            ("price_version" in model, model.get("price_version")),
            ("price_version" in actual_model, actual_model.get("price_version")),
        )
        conflict = {**body, "data": {**body["data"], "unexpected": True}}
        rejection(registry, conflict, after)
        stale = {**body, "operation_id": body["operation_id"] + ".stale"}
        rejection(registry, stale, after)
    for key, expected in grants.items():
        equal("grant persistence", expected, registry.grant(*key))
    for target, expected in history.items():
        equal("immutable price history", expected, registry.prices(target))
    for decision, amount in pinned:
        usage = usage_revision(
            "attempt.generated.price",
            {"input_tokens": 1000000, "output_tokens": 2000000},
            decision=decision,
        )
        equal("historical price attribution", decision["price_version"], usage["price_version"])
        equal(
            "integer historical cost",
            Decimal(nanos(amount)),
            Decimal(usage["cost"]["amount_decimal"]),
        )
    for who in ("svc.demo", "svc.beta"):
        for target, current in models.items():
            grant = grants.get((who, target))
            for purpose, task in (
                ("execution", "class.demo"),
                ("review", "class.demo"),
                ("execution", "class.other"),
            ):
                allowed = current["status"] == "enabled" and bool(
                    grant
                    and grant["status"] == "active"
                    and purpose in grant["purposes"]
                    and task in grant["task_classes"]
                    and purpose in current["purposes"]
                    and task in current["task_classes"]
                )
                equal(
                    "independent grant/model authorization",
                    allowed,
                    registry.explain(who, target, purpose, task)["allowed"],
                )
                if not allowed:
                    try:
                        registry.admit(who, target, purpose, task)
                    except ContractError:
                        pass
                    else:
                        raise Divergence("denied grant admission", "rejection", "accepted")
                else:
                    destination, decision = registry.admit(who, target, purpose, task)
                    equal("admitted destination identity", current["destination"], destination)
                    equal("admitted grant revision", grant["revision"], decision["grant_revision"])
                    expected_price = (
                        history[target][-1]["price_version"]
                        if history[target]
                        else "synthetic.unpriced.v1"
                    )
                    equal(
                        "admitted latest price identity", expected_price, decision["price_version"]
                    )


def run(seed, count):
    run_trace("authority-prices", seed, commands(seed, count), execute)
