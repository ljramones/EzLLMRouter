"""Versioned team overlay on the immutable DEV-09 legacy demo fixture."""
from __future__ import annotations

import json
from pathlib import Path

from .demo_workspace import _amount, _total
from .reporting import _descendants, _group


def project_team_demo(legacy_path, *, collection="team", story="team", actor="", person="", provider=""):
    if collection not in {"team", "expanded"}:
        raise ValueError("invalid demo collection")
    legacy = json.loads(Path(legacy_path).read_text())
    team = json.loads(Path(legacy_path).with_name("dev09_team_demo_fixture.json").read_text())
    if team["legacy_fixture"] != legacy["identity"]:
        raise ValueError("demo fixture version mismatch")
    actors = {item["id"]: item for item in legacy["actors"]}
    actors.update((item["id"], item) for item in team["actor_overrides"])
    for item in team["actors"]:
        if item["id"] in actors:
            raise ValueError("duplicate demo actor")
        actors[item["id"]] = item
    legacy_people = {item["story"]: item["user"] for item in legacy["attempts"]}
    stories = [{**item, "person": legacy_people.get(item["id"])} for item in legacy["stories"]] + team["stories"]
    story_map = {item["id"]: item for item in stories}
    if len(story_map) != len(stories):
        raise ValueError("duplicate demo story")
    legacy_ids = [item["id"] for item in legacy["stories"]]
    team_ids = ["main", *(item["id"] for item in team["stories"])]
    allowed = team_ids + ["team"] if collection == "team" else [*story_map, "expanded_all"]
    if story not in allowed or actor and (actor not in actors or actors[actor]["kind"] != "scripted agent") or \
            person and person != "__autonomous__" and (person not in actors or actors[person]["kind"] != "scripted user") or \
            provider and provider not in legacy["rates"]:
        raise ValueError("invalid demo selector")
    selected = team_ids if story == "team" else list(story_map) if story == "expanded_all" else [story]
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
    source_runs = legacy["runs"] + team["runs"]
    runs = {item["run_id"]: item for item in source_runs}
    if len(runs) != len(source_runs):
        raise ValueError("duplicate demo run")
    def root_run(run_id):
        seen = set()
        while runs[run_id].get("parent_run_id"):
            if run_id in seen:
                raise ValueError("demo run cycle")
            seen.add(run_id)
            run_id = runs[run_id]["parent_run_id"]
        return run_id
    root_story = {item["root_run"]: item["id"] for item in stories}
    attempts, all_attempts, seen = [], [], set()
    for source in legacy["attempts"] + team["attempts"]:
        info = story_map[source["story"]]
        observed = source.get("observed_at", source["at"])
        if source["id"] in seen or not source["id"].startswith("demo.") or \
                source["actor"] not in actors or source["provider"] not in legacy["rates"] or \
                source["run"] not in runs or root_story.get(root_run(source["run"])) != source["story"] or \
                not 0 <= source["start"] < source["at"] <= observed <= info["end"]:
            raise ValueError("invalid demo attempt")
        seen.add(source["id"])
        rate = legacy["rates"][source["provider"]]
        offset = offsets.get(source["story"], 0)
        attempt = {**source, "start": source["start"] + offset, "at": source["at"] + offset,
                   "usage_at": observed + offset, "duration": source["at"] - source["start"],
                   "user": source.get("user", info.get("person")),
                   "owner": source.get("owner", info.get("owner")),
                   "task": source.get("task", info.get("task_id", "demo.task." + source["story"])),
                   "run_id": source["run"], "attempt_id": source["id"],
                   "parent_run_id": runs[source["run"]].get("parent_run_id"),
                   "root_run_id": root_run(source["run"]),
                   "agent_id": runs[source["run"]].get("agent_id"),
                   "model": rate["model"], "rate_ref": "demo.rate.v1." + source["provider"].split(".")[-1],
                   "currency": "USD", "cost_status": "calculated", "amount_decimal": _amount(source, rate),
                   "basis": f"{source['input']} input × USD {rate['input_per_1000_usd']}/1k + "
                            f"{source['output']} output × USD {rate['output_per_1000_usd']}/1k"}
        all_attempts.append(attempt)
        if source["story"] in selected:
            attempts.append(attempt)
    events, event_ids = [], set()
    for source in legacy["events"] + team["events"]:
        if source["id"] in event_ids or not source["id"].startswith("demo.") or \
                source["story"] not in story_map or source["actor"] not in actors or \
                source.get("attempt") and source["attempt"] not in seen or \
                not 0 <= source["at"] <= story_map[source["story"]]["end"]:
            raise ValueError("invalid demo event")
        event_ids.add(source["id"])
        if source["story"] in selected:
            events.append({**source, "at": source["at"] + offsets[source["story"]]})
    for item in attempts:
        if item["story"] not in {s["id"] for s in team["stories"]}:
            continue
        for suffix, when, kind, label, cost_event in (
                ("start", item["start"], "Model call start", item["short"] + " begins", False),
                ("done", item["at"], "Model call complete", item["summary"], item["at"] == item["usage_at"]),
                ("usage", item["usage_at"], "Usage observed", "Usage recorded for " + item["short"], True)):
            if suffix == "usage" and item["usage_at"] == item["at"]:
                continue
            event = {"id": item["id"] + "." + suffix, "story": item["story"], "at": when,
                     "actor": item["actor"], "kind": kind, "label": label, "short": item["short"],
                     "attempt": item["id"], "cost_event": cost_event}
            if event["id"] in event_ids:
                raise ValueError("duplicate demo event")
            event_ids.add(event["id"])
            events.append(event)
    by_attempt = {item["id"]: item for item in attempts}
    for event in events:
        if event.get("attempt") and "cost_event" not in event:
            event["cost_event"] = event["at"] == by_attempt[event["attempt"]]["usage_at"]
    for item in attempts:
        if sum(event.get("attempt") == item["id"] and event.get("cost_event") and
               event["at"] == item["usage_at"] for event in events) != 1:
            raise ValueError("demo attempt needs one usage observation")
    events.sort(key=lambda item: (item["at"], item["id"]))
    attempts.sort(key=lambda item: (item["usage_at"], item["id"]))
    billable = [item for item in attempts if (not actor or item["actor"] == actor) and
                (not person or item["user"] == (None if person == "__autonomous__" else person)) and
                (not provider or item["provider"] == provider)]
    times = sorted({0, end} | {item["at"] for item in events} | {item["usage_at"] for item in billable})
    snapshots = []
    for cutoff in times:
        visible = [item for item in billable if item["usage_at"] <= cutoff]
        full_visible = [item for item in attempts if item["usage_at"] <= cutoff]
        lineage = _descendants([{"attempt_id": a["id"], "run_id": a["run"]} for a in visible], runs)
        workflows = []
        for run in source_runs:
            if root_story[root_run(run["run_id"])] not in selected:
                continue
            direct = [a for a in visible if a["run"] == run["run_id"]]
            inclusive = [a for a in visible if a["id"] in lineage.get(run["run_id"], set())]
            workflows.append({**run, "root_run_id": root_run(run["run_id"]),
                              "direct": _total(direct),
                              "delegated": _total([a for a in inclusive if a["run"] != run["run_id"]]),
                              "inclusive": _total(inclusive)})
        shown = [event for event in events if event["at"] <= cutoff]
        snapshots.append({"at": cutoff, "total": _total(visible), "full_total": _total(full_visible),
                          "attempts": visible,
                          "event_ids": [event["id"] for event in shown],
                          "outcomes": [event for event in shown if event["kind"] in ("Acceptance", "Outcome")],
                          "actor": _group(visible, "actor"), "provider": _group(visible, "provider"),
                          "model": _group(visible, "model"), "user": _group(visible, "user"),
                          "owner": _group(visible, "owner"), "story": _group(visible, "story"),
                          "workflows": workflows})
    return {"identity": team["identity"], "label": "DEMO — scripted activity and simulated USD; no real provider calls",
            "collection": collection, "selected_story": story, "selected_story_ids": selected,
            "selected_actor": actor, "selected_person": person, "selected_provider": provider,
            "actors": list(actors.values()), "rates": legacy["rates"],
            "stories": [{**item, "total": _total([a for a in all_attempts if a["story"] == item["id"]])}
                        for item in stories],
            "all_total": _total(attempts),
            "legacy_total": _total([a for a in all_attempts if a["story"] in legacy_ids]),
            "team_total": _total([a for a in all_attempts if a["story"] in team_ids]),
            "expanded_total": _total(all_attempts),
            "end": end, "events": events, "attempts": attempts, "snapshots": snapshots}
