"""Several registry subjects/actions, exact replay and rejected-write invariants."""

from copy import deepcopy
import random

from ezllmrouter_server.registry import RegistryConflict
from tests.generated_checks import Divergence, equal, run_trace
from tests.operator_console import test_registry as support


def commands(seed, count):
    rng, result = random.Random(seed), []
    subjects = ("cfg.demo", "cfg.beta", "svc.generated.a", "svc.generated.b")
    for index in range(count):
        subject = subjects[index % len(subjects)]
        action = (
            rng.choice(("edit_model", "model_state"))
            if subject.startswith("cfg.")
            else rng.choice(("edit_principal", "principal_state"))
        )
        if action.startswith("edit_"):
            data = {"display_name": f"Generated {rng.randrange(100000)}"}
        else:
            data = {
                "status": rng.choice(("enabled", "disabled"))
                if action == "model_state"
                else "suspended",
                "reason": f"Synthetic {index}",
            }
        result.append({"id": index, "subject": subject, "action": action, "data": data})
    return result


def snapshot(registry, subject):
    return registry.model(subject) if subject.startswith("cfg.") else registry.principal(subject)


def rejected(registry, body, expected, version, rule):
    try:
        registry.mutate("owner.local", body)
    except RegistryConflict:
        pass
    else:
        raise Divergence(rule + " rejection", "RegistryConflict", "accepted")
    equal(rule + " version", version, registry.version())
    equal(rule + " record", expected, snapshot(registry, body["subject"]))


def execute(steps):
    fixture = support.RegistryTests("runTest")
    fixture.setUp()
    try:
        fixture.model_b()
        for subject in ("svc.generated.a", "svc.generated.b"):
            fixture.change(
                "create_principal",
                subject,
                0,
                {"display_name": subject, "kind": "service", "owner": "owner.local"},
            )
        registry = fixture.registry
        subjects = ("cfg.demo", "cfg.beta", "svc.generated.a", "svc.generated.b")
        models = {subject: deepcopy(snapshot(registry, subject)) for subject in subjects}
        version = registry.version()
        for index, command in enumerate(steps):
            try:
                subject, action = command["subject"], command["action"]
                expected = models[subject]
                body = {
                    "operation_id": f"op.generated.{command['id']}",
                    "action": action,
                    "subject": subject,
                    "expected_revision": expected["revision"],
                    "data": command["data"],
                }
                reply = registry.mutate("owner.local", body)
                version += 1
                expected["revision"] += 1
                expected.update(command["data"])
                if action.endswith("_state"):
                    expected["state_reason"] = expected.pop("reason")
                # Approval timestamps are runtime metadata; assert the independently
                # modeled fields, and retain the full result for rejected-write checks.
                actual = snapshot(registry, subject)
                for key in ("revision", "display_name", "status", "owner"):
                    equal("registry " + key, expected[key], actual[key])
                equal("accepted version", version, registry.version())
                equal("operation replay", reply, registry.mutate("owner.local", deepcopy(body)))
                equal("replay version", version, registry.version())
                equal("replay record", actual, snapshot(registry, subject))
                changed = deepcopy(body)
                field = "display_name" if action.startswith("edit_") else "reason"
                changed["data"][field] = "Different synthetic payload"
                rejected(registry, changed, actual, version, "operation ID reuse")
                stale = {**body, "operation_id": f"op.stale.{command['id']}"}
                rejected(registry, stale, actual, version, "stale write")
                for other in subjects:
                    if other != subject:
                        unaffected = snapshot(registry, other)
                        for key in ("revision", "display_name", "status", "owner"):
                            equal("unaffected " + key, models[other][key], unaffected[key])
            except Divergence as error:
                error.index = index
                raise
    finally:
        fixture.doCleanups()


def run(seed, count):
    run_trace("registry", seed, commands(seed, count), execute)
