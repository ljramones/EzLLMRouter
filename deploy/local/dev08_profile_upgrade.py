#!/usr/bin/env python3
"""One-use owner Terminal restart/readback for the persistent DEV-08 profile."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
import sys

import local_profile as profile
from check import wait_health


RUNS = profile.STATE / "dev08-profile-runs"
RUN_ID = re.compile(r"dev08-profile-[0-9]{8}-[0-9]{2,4}\Z")


def claim(run_id):
    if not RUN_ID.fullmatch(run_id):
        raise SystemExit("usage: dev08_profile_upgrade.py dev08-profile-YYYYMMDD-NN")
    path = RUNS / run_id
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=False)
    except FileExistsError:
        raise SystemExit(
            f"run ID already exists: {run_id}; existing result location: "
            f"{path / 'result.json'}; no run was started"
        ) from None
    return path


def snapshot(password, env):
    client, overview = wait_health(password, seconds=10)
    try:
        connections = len(client.call("GET", "/operator/v1/connections")["items"])
    except RuntimeError as exc:
        if not str(exc).startswith("operator 404 "):
            raise
        connections = 0  # The pre-DEV-08 running image has no connection endpoint.
    return {
        "fingerprint": overview["build"]["fingerprint"],
        "commit": overview["build"]["commit"],
        "submissions": overview["counts"]["submissions"],
        "receiver_arrivals": profile.receiver_count(env),
        "provider_connections": connections,
    }


def running_build(password):
    _, overview = wait_health(password, seconds=10)
    fingerprint = overview["build"]["fingerprint"]
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise RuntimeError("running profile fingerprint invalid")
    manifest = (
        profile.STATE / "staging" / ("source-" + fingerprint[:16]) / "LOCAL-BUILD-MANIFEST.json"
    )
    if not manifest.is_file():
        raise RuntimeError("running profile staged source manifest missing")
    build = json.loads(manifest.read_text())
    if (
        build.get("fingerprint") != fingerprint
        or build.get("commit") != overview["build"]["commit"]
        or not os.path.isdir(build.get("build_dir", ""))
    ):
        raise RuntimeError("running profile staged source identity mismatch")
    return build


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: dev08_profile_upgrade.py dev08-profile-YYYYMMDD-NN")
    run_id = sys.argv[1]
    path = claim(run_id)
    stages = []
    try:
        _, password = profile.secrets_on_disk()
        old = running_build(password)
        old_env = profile.environment(old)
        profile.ensure_owner(old_env)
        before = snapshot(password, old_env)
        if before["fingerprint"] != old["fingerprint"]:
            raise RuntimeError("running profile differs from staged source")
        stages.append("read-running-identity")
        profile.backup_live_store(old_env)
        stages.append("online-backup")
        profile.command(
            "dev08-profile-prepare",
            [sys.executable, "-I", "-B", str(profile.LOCAL / "prepare.py")],
            env=os.environ.copy(),
        )
        build = profile.current()
        if build["dirty"]:
            raise RuntimeError("staged DEV-08 source is dirty")
        env = profile.environment(build)
        stages.append("prepare-clean-source")
        profile.build_images(build, env)
        stages.append("build-frozen-images")
        profile.command(
            "dev08-profile-stop", profile.compose_args("down", "--remove-orphans"), old_env
        )
        stages.append("stop")
        profile.command("dev08-profile-up", profile.compose_args("up", "-d", "--no-build"), env)
        profile.check_console_port(env)
        after = snapshot(password, env)
        if after["fingerprint"] != build["fingerprint"]:
            raise RuntimeError("running profile source identity mismatch")
        profile.topology(env)
        if (
            after["submissions"] != before["submissions"]
            or after["receiver_arrivals"] != before["receiver_arrivals"]
            or after["provider_connections"] != before["provider_connections"]
            or profile.receiver_count(env) != before["receiver_arrivals"]
        ):
            raise RuntimeError("restart changed submissions, connections or receiver arrivals")
        stages.append("restart-readback-and-isolation")
        result = {
            "kind": "DEV-08 persistent profile code update and readback",
            "status": "PASS",
            "run_id": run_id,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "before": before,
            "after": after,
            "source_commit": build["commit"],
            "fingerprint": build["fingerprint"],
            "stages": stages,
            "model_requests_added": 0,
            "actual_provider_validation_performed": False,
        }
        (path / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(json.dumps(result, sort_keys=True))
    except Exception as exc:
        (path / "failure.json").write_text(
            json.dumps(
                {
                    "status": "FAILED",
                    "run_id": run_id,
                    "stages_completed": stages,
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:250],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        raise


if __name__ == "__main__":
    main()
