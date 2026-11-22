"""Lazy deterministic JSON reductions with a single bounded predicate budget."""

from copy import deepcopy
import json
import math


def deletions(value):
    width = max(1, len(value) // 2)
    while width:
        for start in range(0, len(value), width):
            yield value[:start] + value[start + width :]
        width //= 2


def candidates(value):
    if type(value) in (list, dict):
        if isinstance(value, list):
            yield from deletions(value)
            for index, child in enumerate(value):
                for smaller in candidates(child):
                    yield value[:index] + [smaller] + value[index + 1 :]
        else:
            keys = list(value)
            for remaining in deletions(keys):
                yield {key: value[key] for key in remaining}
            for key, child in value.items():
                for smaller in candidates(child):
                    yield {**value, key: smaller}
                for smaller in deletions(key):
                    if smaller not in value:
                        yield {
                            smaller if name == key else name: item for name, item in value.items()
                        }
    elif type(value) is str:
        yield from deletions(value)
    elif type(value) is bool:
        yield False
    elif type(value) is int:
        yield 0
        yield 1 if value > 0 else -1
        delta = abs(value)
        while delta:
            yield value - (delta if value > 0 else -delta)
            delta //= 2
    elif type(value) is float and math.isfinite(value):
        yield 0.0
        yield float(int(value))
        yield int(value)


def minimize(value, fails, budget=48, stats=None):
    if not 0 <= budget <= 10000:
        raise ValueError("invalid JSON shrink budget")
    candidate, attempts, seen = deepcopy(value), 0, set()

    def identity(item):
        return json.dumps(item, ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    def weight(item):
        if isinstance(item, (dict, list)):
            children = list(item) + list(item.values()) if isinstance(item, dict) else item
            costs = [weight(child) for child in children]
            return (
                1 + sum(c[0] for c in costs),
                sum(c[1] for c in costs),
                sum(c[2] for c in costs),
                len(identity(item)),
            )
        return (
            1,
            len(item) if type(item) is str else 0,
            abs(item) if type(item) in (int, float, bool) else 0,
            len(identity(item)),
        )

    while attempts < budget:
        for trial in candidates(candidate):
            token = identity(trial)
            if weight(trial) >= weight(candidate) or token in seen:
                continue
            seen.add(token)
            attempts += 1
            if fails(trial):
                candidate = trial
                break
            if attempts >= budget:
                break
        else:
            break
    if stats is not None:
        stats.update(
            attempts=attempts,
            budget=budget,
            scope="command deletion and recursive JSON/scalar reduction",
        )
    return candidate
