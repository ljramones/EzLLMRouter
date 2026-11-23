"""CVSS v4 base scoring adapted from FIRST's BSD-2-Clause reference calculator.

Source: FIRSTdotorg/cvss-v4-calculator at c5b0d409ae9f57c44264c6ce5f27d89298e1d32a.
The accompanying JSON retains the reviewed normative tables and source hashes;
security_cvss4_LICENSE.txt contains the copyright notice, terms and disclaimer.
Only base metrics affect this score. Full vectors are validated before scoring.
"""

from functools import lru_cache, reduce
import hashlib
from itertools import product
import json
import math
from operator import add
from pathlib import Path
from typing import Any

DATA_SHA256 = "98f5a3db3ad05b6c2d208e89cff15e860797db3a2517d0672cd604b88cc1482c"
BASE = ("AV", "AC", "AT", "PR", "UI", "VC", "VI", "VA", "SC", "SI", "SA")
GROUPS = (
    ("AV", "PR", "UI"),
    ("AC", "AT"),
    ("VC", "VI", "VA", "CR", "IR", "AR"),
    ("SC", "SI", "SA"),
)
LEVELS = {
    "AV": "NALP",
    "PR": "NLH",
    "UI": "NPA",
    "AC": "LH",
    "AT": "NP",
    **{key: "HLN" for key in ("VC", "VI", "VA", "SC", "SI", "SA")},
    **{key: "HML" for key in ("CR", "IR", "AR")},
}
WEIGHTS = {
    key: {value: (index + (key in {"SC", "SI", "SA"})) / 10 for index, value in enumerate(values)}
    for key, values in LEVELS.items()
}


@lru_cache(maxsize=1)
def data() -> dict[str, Any]:
    raw = Path(__file__).with_name("security_cvss4_data.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != DATA_SHA256:
        raise ValueError("unreviewed CVSS v4 normative data")
    result: dict[str, Any] = json.loads(raw)
    return result


def parse(vector: str) -> dict[str, str]:
    if not isinstance(vector, str) or len(vector) > 2048:
        raise ValueError("invalid CVSS v4 vector")
    prefix, *entries = vector.split("/")
    if prefix != "CVSS:4.0":
        raise ValueError("unsupported CVSS version")
    allowed = data()["metrics"]
    order = tuple(allowed)
    metrics = {}
    previous = -1
    for entry in entries:
        pair = entry.split(":")
        if len(pair) != 2 or pair[0] not in allowed or pair[1] not in allowed[pair[0]]:
            raise ValueError("invalid CVSS v4 metric")
        index = order.index(pair[0])
        if index <= previous:
            raise ValueError("duplicate or out-of-order CVSS v4 metric")
        metrics[pair[0]] = pair[1]
        previous = index
    if not set(BASE) <= metrics.keys():
        raise ValueError("incomplete CVSS v4 base vector")
    return metrics


def base_score(vector: str) -> float:
    full = parse(vector)
    # FIRST defaults E to A and requirements to H for CVSS-B. Modified and
    # supplemental values remain retained/validated in full, outside this score.
    selected = {key: full[key] for key in BASE} | {"E": "A", "CR": "H", "IR": "H", "AR": "H"}
    if all(selected[key] == "N" for key in BASE[5:]):
        return 0.0
    direct = (selected["AV"] == "N", selected["PR"] == "N", selected["UI"] == "N")
    high = [selected[key] == "H" for key in ("VC", "VI", "VA")]
    eqs = [
        0 if all(direct) else 1 if any(direct) and selected["AV"] != "P" else 2,
        0 if selected["AC"] == "L" and selected["AT"] == "N" else 1,
        0 if high[0] and high[1] else 1 if any(high) else 2,
        1 if any(selected[key] == "H" for key in ("SC", "SI", "SA")) else 2,
        0,
        0 if any(high) else 1,
    ]
    tables = data()
    lookup = tables["lookup"]
    macro = "".join(map(str, eqs))
    value = float(lookup[macro])

    def lower(*positions: int) -> float | None:
        candidate = eqs.copy()
        for index in positions:
            candidate[index] += 1
        found = lookup.get("".join(map(str, candidate)))
        return None if found is None else float(found)

    joint: float | None
    if eqs[2] == 0 and eqs[5] == 0:
        candidates = [lower(5), lower(2)]
        joint = max(score for score in candidates if score is not None)
    elif eqs[2] == 1 and eqs[5] == 0:
        joint = lower(5)
    else:
        joint = lower(2, 5)
    lowers = (lower(0), lower(1), joint, lower(3), lower(4))
    composed = tables["max_composed"]
    maxima = (
        composed["eq1"][str(eqs[0])],
        composed["eq2"][str(eqs[1])],
        composed["eq3"][str(eqs[2])][str(eqs[5])],
        composed["eq4"][str(eqs[3])],
    )
    distances = None
    for parts in product(*maxima):
        maximum = dict(entry.split(":") for entry in "".join(parts).rstrip("/").split("/"))
        differences = {
            key: weights[selected[key]] - weights[maximum[key]] for key, weights in WEIGHTS.items()
        }
        if all(distance >= 0 for distance in differences.values()):
            distances = [reduce(add, (differences[key] for key in group), 0.0) for group in GROUPS]
            break
    if distances is None:
        raise ValueError("CVSS v4 vector has no dominating reference maximum")
    depths = tables["max_severity"]
    maximum_distances = (
        depths["eq1"][str(eqs[0])],
        depths["eq2"][str(eqs[1])],
        depths["eq3eq6"][str(eqs[2])][str(eqs[5])],
        depths["eq4"][str(eqs[3])],
    )
    normalized = [
        (value - next_score) * (distance / (depth * 0.1))
        for next_score, distance, depth in zip(
            lowers[:4], distances, maximum_distances, strict=True
        )
        if next_score is not None
    ]
    # The threat-group distance is zero for CVSS-B, but an existing lower
    # MacroVector still contributes to the reference algorithm's divisor.
    count = sum(score is not None for score in lowers)
    # Preserve FIRST's left-to-right IEEE-754 operations. Python 3.12 sum uses
    # compensated floating summation, and round uses ties-to-even; neither
    # reproduces the reference calculator at half-tenth boundaries.
    score = max(0.0, min(10.0, value - (reduce(add, normalized, 0.0) / count if count else 0.0)))
    scaled = score * 10
    floor = math.floor(scaled)
    return (floor + (scaled - floor >= 0.5)) / 10
