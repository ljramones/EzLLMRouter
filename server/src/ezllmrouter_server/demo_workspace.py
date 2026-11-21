"""Read-only projection of the fixed DEV-09 scripted demonstration."""

from __future__ import annotations

import json
from pathlib import Path
from .store import Record

from .reporting import descendant_attempts, group_attempts
from .demo_common import LABEL, amount, total, basis, select_attempts


def project_demo(
    fixture_path: str | Path,
    *,
    story: str = "main",
    actor: str = "",
    person: str = "",
    provider: str = "",
) -> Record:
    """Build immutable playback snapshots; no registry or provider is consulted."""
    fixture = json.loads(Path(fixture_path).read_text())
    stories, story_ids, actor_ids, providers = _legacy_identity(
        fixture, story, actor, person, provider
    )
    runs = {item["run_id"]: item for item in fixture["runs"]}
    offsets, end = _legacy_timeline(stories, story)
    attempts, seen = _legacy_attempts(
        fixture, stories, story_ids, actor_ids, providers, runs, offsets, story
    )
    events = _legacy_events(fixture, story_ids, actor_ids, seen, story, offsets, attempts)
    selected = select_attempts(attempts, actor, person, provider)
    all_attempts, story_totals = _legacy_reference_totals(fixture, providers, stories)
    # A projection of the full, unfiltered fixture is reference context, never an extra charge.
    snapshots = _legacy_snapshots(end, events, attempts, runs, fixture, story, selected)
    return {
        "identity": fixture["identity"],
        "label": LABEL,
        "collection": "legacy",
        "stories": story_totals,
        "selected_story": story,
        "selected_story_ids": [item["id"] for item in stories] if story == "all" else [story],
        "selected_actor": actor,
        "selected_person": person,
        "selected_provider": provider,
        "actors": fixture["actors"],
        "rates": providers,
        "all_total": total(all_attempts),
        "end": end,
        "events": events,
        "attempts": attempts,
        "snapshots": snapshots,
    }


def _legacy_identity(
    fixture: Record, story: str, actor: str, person: str, provider: str
) -> tuple[list[Record], set[str], set[str], dict[str, Record]]:
    stories = fixture["stories"]
    story_ids = {item["id"] for item in stories}
    actor_ids = {item["id"] for item in fixture["actors"]}
    providers = fixture["rates"]
    if (
        story not in story_ids | {"all"}
        or actor
        and actor not in actor_ids
        or person
        and person not in actor_ids | {"__autonomous__"}
        or provider
        and provider not in providers
    ):
        raise ValueError("invalid demo filter")
    if person and person != "__autonomous__" and not person.startswith("demo.user."):
        raise ValueError("invalid demo person")
    if len(story_ids) != len(stories) or len(actor_ids) != len(fixture["actors"]):
        raise ValueError("duplicate demo identity")
    return stories, story_ids, actor_ids, providers


def _legacy_timeline(stories: list[Record], story: str) -> tuple[dict[str, int], int]:
    offsets = {}
    elapsed = 0
    for item in stories:
        offsets[item["id"]] = elapsed
        elapsed += item["end"] + 10
    end = (
        elapsed - 10
        if story == "all"
        else next(item["end"] for item in stories if item["id"] == story)
    )
    return offsets, end


def _legacy_attempts(
    fixture: Record,
    stories: list[Record],
    story_ids: set[str],
    actor_ids: set[str],
    providers: dict[str, Record],
    runs: dict[str, Record],
    offsets: dict[str, int],
    story: str,
) -> tuple[list[Record], set[str]]:
    attempts = []
    seen = set()
    for source in fixture["attempts"]:
        if (
            source["id"] in seen
            or not source["id"].startswith("demo.")
            or source["story"] not in story_ids
            or source["actor"] not in actor_ids
            or source["provider"] not in providers
            or source["run"] not in runs
            or not 0
            <= source["start"]
            < source["at"]
            <= next(s["end"] for s in stories if s["id"] == source["story"])
        ):
            raise ValueError("invalid demo attempt")
        seen.add(source["id"])
        rate = providers[source["provider"]]
        attempt = {
            **source,
            "at": source["at"] + (offsets[source["story"]] if story == "all" else 0),
            "start": source["start"] + (offsets[source["story"]] if story == "all" else 0),
            "usage_at": source["at"] + (offsets[source["story"]] if story == "all" else 0),
            "duration": source["at"] - source["start"],
            "model": rate["model"],
            "rate_ref": "demo.rate.v1." + source["provider"].split(".")[-1],
            "parent_run_id": runs[source["run"]].get("parent_run_id"),
            "root_run_id": next(s["root_run"] for s in stories if s["id"] == source["story"]),
            "agent_id": runs[source["run"]].get("agent_id"),
            "currency": "USD",
            "cost_status": "calculated",
            "amount_decimal": amount(source, rate),
            "basis": basis(source, rate),
            "attempt_id": source["id"],
            "run_id": source["run"],
        }
        if story == "all" or source["story"] == story:
            attempts.append(attempt)
    return attempts, seen


def _legacy_events(
    fixture: Record,
    story_ids: set[str],
    actor_ids: set[str],
    seen: set[str],
    story: str,
    offsets: dict[str, int],
    attempts: list[Record],
) -> list[Record]:
    events = []
    event_ids = set()
    for source in fixture["events"]:
        if (
            source["id"] in event_ids
            or not source["id"].startswith("demo.")
            or source["story"] not in story_ids
            or source["actor"] not in actor_ids
            or source.get("attempt")
            and source["attempt"] not in seen
        ):
            raise ValueError("invalid demo event")
        event_ids.add(source["id"])
        if story == "all" or source["story"] == story:
            events.append(
                {**source, "at": source["at"] + (offsets[source["story"]] if story == "all" else 0)}
            )
    events.sort(key=lambda item: (item["at"], item["id"]))
    attempts.sort(key=lambda item: (item["at"], item["id"]))
    for attempt in attempts:
        if (
            sum(
                event.get("attempt") == attempt["id"] and event["at"] == attempt["at"]
                for event in events
            )
            != 1
        ):
            raise ValueError("demo attempt has no unique completion event")
    return events


def _legacy_reference_totals(
    fixture: Record, providers: dict[str, Record], stories: list[Record]
) -> tuple[list[Record], list[Record]]:
    all_attempts = []
    for source in fixture["attempts"]:
        all_attempts.append(
            {
                "cost_status": "calculated",
                "currency": "USD",
                "amount_decimal": amount(source, providers[source["provider"]]),
            }
        )
    story_totals = [
        {
            "id": item["id"],
            "name": item["name"],
            "end": item["end"],
            "outcome": item["outcome"],
            "task_class": item["task_class"],
            "root_run": item["root_run"],
            "total": total(
                [
                    computed
                    for source, computed in zip(fixture["attempts"], all_attempts, strict=True)
                    if source["story"] == item["id"]
                ]
            ),
        }
        for item in stories
    ]
    return all_attempts, story_totals


def _legacy_snapshots(
    end: int,
    events: list[Record],
    attempts: list[Record],
    runs: dict[str, Record],
    fixture: Record,
    story: str,
    selected: list[Record],
) -> list[Record]:
    snapshot_times = sorted(
        {0, end} | {item["at"] for item in events} | {item["at"] for item in selected}
    )
    snapshots = []
    for cutoff in snapshot_times:
        visible = [item for item in selected if item["at"] <= cutoff]
        visible_events = [item["id"] for item in events if item["at"] <= cutoff]
        lineage_rows = [{"attempt_id": item["id"], "run_id": item["run"]} for item in visible]
        descendants = descendant_attempts(lineage_rows, runs)
        workflows = []
        for run in fixture["runs"]:
            if story != "all" and not any(a["run"] == run["run_id"] for a in attempts):
                continue
            direct = [item for item in visible if item["run"] == run["run_id"]]
            inclusive = [
                item for item in visible if item["id"] in descendants.get(run["run_id"], set())
            ]
            delegated = [item for item in inclusive if item["run"] != run["run_id"]]
            workflows.append(
                {
                    **run,
                    "direct": total(direct),
                    "delegated": total(delegated),
                    "inclusive": total(inclusive),
                }
            )
        full_visible = [item for item in attempts if item["at"] <= cutoff]
        snapshots.append(
            {
                "at": cutoff,
                "total": total(visible),
                "full_total": total(full_visible),
                "attempts": visible,
                "event_ids": visible_events,
                "actor": group_attempts(visible, "actor"),
                "provider": group_attempts(visible, "provider"),
                "model": group_attempts(visible, "model"),
                "user": group_attempts(visible, "user"),
                "owner": group_attempts(visible, "owner"),
                "workflows": workflows,
            }
        )
    return snapshots
