"""Versioned team overlay on the immutable DEV-09 legacy demo fixture."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast
from collections.abc import Callable
from .store import Record

from .demo_common import LABEL, amount, total, basis, select_attempts
from .reporting import descendant_attempts, group_attempts


def project_team_demo(
    legacy_path: str | Path,
    *,
    collection: str = "team",
    story: str = "team",
    actor: str = "",
    person: str = "",
    provider: str = "",
) -> Record:
    if collection not in {"team", "expanded"}:
        raise ValueError("invalid demo collection")
    legacy = json.loads(Path(legacy_path).read_text())
    team = json.loads(Path(legacy_path).with_name("dev09_team_demo_fixture.json").read_text())
    if team["legacy_fixture"] != legacy["identity"]:
        raise ValueError("demo fixture version mismatch")
    actors, stories, story_map, legacy_ids, team_ids, selected = _team_selection(
        legacy, team, collection, story, actor, person, provider
    )
    offsets, end = _team_timeline(team, story, story_map, legacy_ids, selected)
    source_runs, runs, root_run = _team_runs(legacy, team)

    root_story = {item["root_run"]: item["id"] for item in stories}
    attempts, all_attempts, seen = _team_attempts(
        legacy, team, story_map, actors, runs, root_story, root_run, offsets, selected
    )
    events = _team_events(legacy, team, story_map, actors, seen, selected, offsets, attempts)
    billable = select_attempts(attempts, actor, person, provider)
    snapshots = _team_snapshots(
        end, events, billable, attempts, runs, source_runs, root_story, root_run, selected
    )
    return {
        "identity": team["identity"],
        "label": LABEL,
        "collection": collection,
        "selected_story": story,
        "selected_story_ids": selected,
        "selected_actor": actor,
        "selected_person": person,
        "selected_provider": provider,
        "actors": list(actors.values()),
        "rates": legacy["rates"],
        "stories": [
            {**item, "total": total([a for a in all_attempts if a["story"] == item["id"]])}
            for item in stories
        ],
        "all_total": total(attempts),
        "legacy_total": total([a for a in all_attempts if a["story"] in legacy_ids]),
        "team_total": total([a for a in all_attempts if a["story"] in team_ids]),
        "expanded_total": total(all_attempts),
        "end": end,
        "events": events,
        "attempts": attempts,
        "snapshots": snapshots,
    }


def _team_selection(
    legacy: Record,
    team: Record,
    collection: str,
    story: str,
    actor: str,
    person: str,
    provider: str,
) -> tuple[dict[str, Record], list[Record], dict[str, Record], list[str], list[str], list[str]]:
    actors = {item["id"]: item for item in legacy["actors"]}
    actors.update((item["id"], item) for item in team["actor_overrides"])
    for item in team["actors"]:
        if item["id"] in actors:
            raise ValueError("duplicate demo actor")
        actors[item["id"]] = item
    legacy_people = {item["story"]: item["user"] for item in legacy["attempts"]}
    stories = [
        {**item, "person": legacy_people.get(item["id"])} for item in legacy["stories"]
    ] + team["stories"]
    story_map = {item["id"]: item for item in stories}
    if len(story_map) != len(stories):
        raise ValueError("duplicate demo story")
    legacy_ids = [item["id"] for item in legacy["stories"]]
    team_ids = ["main", *(item["id"] for item in team["stories"])]
    allowed = team_ids + ["team"] if collection == "team" else [*story_map, "expanded_all"]
    if (
        story not in allowed
        or actor
        and (actor not in actors or actors[actor]["kind"] != "scripted agent")
        or person
        and person != "__autonomous__"
        and (person not in actors or actors[person]["kind"] != "scripted user")
        or provider
        and provider not in legacy["rates"]
    ):
        raise ValueError("invalid demo selector")
    selected = (
        team_ids if story == "team" else list(story_map) if story == "expanded_all" else [story]
    )
    return actors, stories, story_map, legacy_ids, team_ids, selected


def _team_timeline(
    team: Record,
    story: str,
    story_map: dict[str, Record],
    legacy_ids: list[str],
    selected: list[str],
) -> tuple[dict[str, int], int]:
    if story in {"team", "expanded_all"}:
        offsets = dict(team["team_offsets_seconds"])
        if story == "expanded_all":
            cursor = max(offsets[name] + story_map[name]["end"] for name in offsets)
            for name in legacy_ids:
                if name != "main":
                    cursor += 10
                    offsets[name] = cursor
                    cursor += story_map[name]["end"]
    else:
        offsets = {story: 0}
    end = max(offsets[name] + story_map[name]["end"] for name in selected)
    return offsets, end


def _team_runs(
    legacy: Record, team: Record
) -> tuple[list[Record], dict[str, Record], Callable[[str], str]]:
    source_runs = legacy["runs"] + team["runs"]
    runs = {item["run_id"]: item for item in source_runs}
    if len(runs) != len(source_runs):
        raise ValueError("duplicate demo run")

    def root_run(run_id: str) -> str:
        seen = set()
        while runs[run_id].get("parent_run_id"):
            if run_id in seen:
                raise ValueError("demo run cycle")
            seen.add(run_id)
            run_id = runs[run_id]["parent_run_id"]
        return run_id

    return source_runs, runs, root_run


def _team_attempts(
    legacy: Record,
    team: Record,
    story_map: dict[str, Record],
    actors: dict[str, Record],
    runs: dict[str, Record],
    root_story: dict[str, str],
    root_run: Callable[[str], str],
    offsets: dict[str, int],
    selected: list[str],
) -> tuple[list[Record], list[Record], set[str]]:
    attempts, all_attempts, seen = [], [], set()
    for source in legacy["attempts"] + team["attempts"]:
        info = story_map[source["story"]]
        observed = source.get("observed_at", source["at"])
        if (
            source["id"] in seen
            or not source["id"].startswith("demo.")
            or source["actor"] not in actors
            or source["provider"] not in legacy["rates"]
            or source["run"] not in runs
            or root_story.get(root_run(source["run"])) != source["story"]
            or not 0 <= source["start"] < source["at"] <= observed <= info["end"]
        ):
            raise ValueError("invalid demo attempt")
        seen.add(source["id"])
        rate = legacy["rates"][source["provider"]]
        offset = offsets.get(source["story"], 0)
        attempt = {
            **source,
            "start": source["start"] + offset,
            "at": source["at"] + offset,
            "usage_at": observed + offset,
            "duration": source["at"] - source["start"],
            "user": source.get("user", info.get("person")),
            "owner": source.get("owner", info.get("owner")),
            "task": source.get("task", info.get("task_id", "demo.task." + source["story"])),
            "run_id": source["run"],
            "attempt_id": source["id"],
            "parent_run_id": runs[source["run"]].get("parent_run_id"),
            "root_run_id": root_run(source["run"]),
            "agent_id": runs[source["run"]].get("agent_id"),
            "model": rate["model"],
            "rate_ref": "demo.rate.v1." + source["provider"].split(".")[-1],
            "currency": "USD",
            "cost_status": "calculated",
            "amount_decimal": amount(source, rate),
            "basis": basis(source, rate),
        }
        all_attempts.append(attempt)
        if source["story"] in selected:
            attempts.append(attempt)
    return attempts, all_attempts, seen


def _team_events(
    legacy: Record,
    team: Record,
    story_map: dict[str, Record],
    actors: dict[str, Record],
    seen: set[str],
    selected: list[str],
    offsets: dict[str, int],
    attempts: list[Record],
) -> list[Record]:
    events, event_ids = [], set()
    for source in legacy["events"] + team["events"]:
        if (
            source["id"] in event_ids
            or not source["id"].startswith("demo.")
            or source["story"] not in story_map
            or source["actor"] not in actors
            or source.get("attempt")
            and source["attempt"] not in seen
            or not 0 <= source["at"] <= story_map[source["story"]]["end"]
        ):
            raise ValueError("invalid demo event")
        event_ids.add(source["id"])
        if source["story"] in selected:
            events.append({**source, "at": source["at"] + offsets[source["story"]]})
    for item in attempts:
        if item["story"] not in {s["id"] for s in team["stories"]}:
            continue
        for suffix, when, kind, label, cost_event in (
            ("start", item["start"], "Model call start", item["short"] + " begins", False),
            (
                "done",
                item["at"],
                "Model call complete",
                item["summary"],
                item["at"] == item["usage_at"],
            ),
            (
                "usage",
                item["usage_at"],
                "Usage observed",
                "Usage recorded for " + item["short"],
                True,
            ),
        ):
            if suffix == "usage" and item["usage_at"] == item["at"]:
                continue
            event = {
                "id": item["id"] + "." + suffix,
                "story": item["story"],
                "at": when,
                "actor": item["actor"],
                "kind": kind,
                "label": label,
                "short": item["short"],
                "attempt": item["id"],
                "cost_event": cost_event,
            }
            if event["id"] in event_ids:
                raise ValueError("duplicate demo event")
            event_ids.add(event["id"])
            events.append(event)
    by_attempt = {item["id"]: item for item in attempts}
    for event in events:
        if event.get("attempt") and "cost_event" not in event:
            event["cost_event"] = event["at"] == by_attempt[event["attempt"]]["usage_at"]
    for item in attempts:
        if (
            sum(
                event.get("attempt") == item["id"]
                and cast(bool, event.get("cost_event"))
                and event["at"] == item["usage_at"]
                for event in events
            )
            != 1
        ):
            raise ValueError("demo attempt needs one usage observation")
    events.sort(key=lambda item: (item["at"], item["id"]))
    attempts.sort(key=lambda item: (item["usage_at"], item["id"]))
    return events


def _team_snapshots(
    end: int,
    events: list[Record],
    billable: list[Record],
    attempts: list[Record],
    runs: dict[str, Record],
    source_runs: list[Record],
    root_story: dict[str, str],
    root_run: Callable[[str], str],
    selected: list[str],
) -> list[Record]:
    times = sorted(
        {0, end} | {item["at"] for item in events} | {item["usage_at"] for item in billable}
    )
    snapshots = []
    for cutoff in times:
        visible = [item for item in billable if item["usage_at"] <= cutoff]
        full_visible = [item for item in attempts if item["usage_at"] <= cutoff]
        lineage = descendant_attempts(
            [{"attempt_id": a["id"], "run_id": a["run"]} for a in visible], runs
        )
        workflows = []
        for run in source_runs:
            if root_story[root_run(run["run_id"])] not in selected:
                continue
            direct = [a for a in visible if a["run"] == run["run_id"]]
            inclusive = [a for a in visible if a["id"] in lineage.get(run["run_id"], set())]
            workflows.append(
                {
                    **run,
                    "root_run_id": root_run(run["run_id"]),
                    "direct": total(direct),
                    "delegated": total([a for a in inclusive if a["run"] != run["run_id"]]),
                    "inclusive": total(inclusive),
                }
            )
        shown = [event for event in events if event["at"] <= cutoff]
        snapshots.append(
            {
                "at": cutoff,
                "total": total(visible),
                "full_total": total(full_visible),
                "attempts": visible,
                "event_ids": [event["id"] for event in shown],
                "outcomes": [
                    event for event in shown if event["kind"] in ("Acceptance", "Outcome")
                ],
                "actor": group_attempts(visible, "actor"),
                "provider": group_attempts(visible, "provider"),
                "model": group_attempts(visible, "model"),
                "user": group_attempts(visible, "user"),
                "owner": group_attempts(visible, "owner"),
                "story": group_attempts(visible, "story"),
                "workflows": workflows,
            }
        )
    return snapshots
