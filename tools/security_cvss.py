"""CVSS v3 base scores, using the FIRST v3.0/v3.1 equations and exact arithmetic.

Specification: https://www.first.org/cvss/v3.1/specification-document
Temporal/environmental metrics are validated but never reduce this base-score gate.
Other CVSS versions deliberately remain unsupported and fail closed in the caller.
"""

from fractions import Fraction
from typing import Any

VALUES = {
    "AV": "NALP",
    "AC": "LH",
    "PR": "NLH",
    "UI": "NR",
    "S": "UC",
    "C": "HLN",
    "I": "HLN",
    "A": "HLN",
    "E": "XUPFH",
    "RL": "XOTWU",
    "RC": "XURC",
    "CR": "XHML",
    "IR": "XHML",
    "AR": "XHML",
    "MAV": "XNALP",
    "MAC": "XLH",
    "MPR": "XNLH",
    "MUI": "XNR",
    "MS": "XUC",
    "MC": "XHLN",
    "MI": "XHLN",
    "MA": "XHLN",
}


def base_score(vector: str) -> float:
    if not isinstance(vector, str) or len(vector) > 1024:
        raise ValueError("invalid CVSS vector")
    prefix, *entries = vector.split("/")
    if prefix not in {"CVSS:3.0", "CVSS:3.1"}:
        raise ValueError("unsupported CVSS version")
    metrics = {}
    for entry in entries:
        pair = entry.split(":")
        if (
            len(pair) != 2
            or pair[0] not in VALUES
            or pair[0] in metrics
            or len(pair[1]) != 1
            or pair[1] not in VALUES[pair[0]]
        ):
            raise ValueError("invalid CVSS metric")
        metrics[pair[0]] = pair[1]
    if not set("AV AC PR UI S C I A".split()) <= metrics.keys():
        raise ValueError("incomplete CVSS base vector")

    def weight(metric: str, values: dict[str, str]) -> Fraction:
        return Fraction(values[metrics[metric]])

    impacts = {"H": ".56", "L": ".22", "N": "0"}
    iss = 1 - (1 - weight("C", impacts)) * (1 - weight("I", impacts)) * (1 - weight("A", impacts))
    changed = metrics["S"] == "C"
    impact = (
        Fraction("7.52") * (iss - Fraction(".029"))
        - Fraction("3.25") * (iss - Fraction(".02")) ** 15
        if changed
        else Fraction("6.42") * iss
    )
    if impact <= 0:
        return 0.0
    exploitability = (
        Fraction("8.22")
        * weight("AV", {"N": ".85", "A": ".62", "L": ".55", "P": ".2"})
        * weight("AC", {"L": ".77", "H": ".44"})
        * weight(
            "PR", {"N": ".85", "L": ".68" if changed else ".62", "H": ".5" if changed else ".27"}
        )
        * weight("UI", {"N": ".85", "R": ".62"})
    )
    score = min(Fraction(10), (impact + exploitability) * (Fraction("1.08") if changed else 1))
    # FIRST Roundup, exactly: the smallest tenth at least as large as the score.
    tenths = score * 10
    return ((tenths.numerator + tenths.denominator - 1) // tenths.denominator) / 10


def classification(detail: dict[str, Any]) -> dict[str, Any]:
    database = detail.get("database_specific", {})
    database = database.get("severity", "UNRATED") if isinstance(database, dict) else "UNRATED"
    levels = {"NONE": 0, "LOW": 1, "MODERATE": 2, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
    database = database if isinstance(database, str) and database in levels else "UNRATED"
    effective = "MODERATE" if database == "MEDIUM" else database
    scores = []
    invalid = False
    ratings = detail.get("severity", [])
    if not isinstance(ratings, list):
        ratings, invalid = [], True
    for rating in ratings:
        try:
            if not isinstance(rating, dict) or rating.get("type") != "CVSS_V3":
                raise ValueError("unsupported severity type")
            vector = rating.get("score")
            if not isinstance(vector, str):
                raise ValueError("invalid CVSS vector")
            score = base_score(vector)
            severity = (
                "CRITICAL"
                if score >= 9
                else "HIGH"
                if score >= 7
                else "MODERATE"
                if score >= 4
                else "LOW"
                if score > 0
                else "NONE"
            )
            scores.append({"type": "CVSS_V3", "base_score": score, "severity": severity})
            if effective == "UNRATED" or levels[severity] > levels[effective]:
                effective = severity
        except ValueError:
            invalid = True
    if invalid:
        effective = "UNRATED"
    return {
        "database_severity": database,
        "effective_severity": effective,
        "cvss_base_scores": scores,
        "unsupported_or_invalid_rating": invalid,
        "blocking": effective in {"HIGH", "CRITICAL", "UNRATED"},
    }
