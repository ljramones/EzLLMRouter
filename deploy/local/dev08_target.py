#!/usr/bin/env python3
"""One-use owner Docker build discriminator; leaves the running profile untouched."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import local_profile
from command_support import target_command


ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "deploy/local/.state/dev08-runs"


def command(name, argv, run):
    _, code = target_command(
        name,
        argv,
        run,
        cwd=ROOT,
        env=os.environ.copy(),
        redact=local_profile.redact,
        label="DEV-08 target",
        records=local_profile.STATE / "commands",
        timeout=900,
        allowed=tuple(range(256)),
    )
    return code


def main():
    if len(sys.argv) != 2 or not re.fullmatch(r"dev08-[0-9]{8}-[0-9]{2}", sys.argv[1]):
        raise SystemExit("usage: dev08_target.py dev08-YYYYMMDD-NN")
    if not os.environ.get("EZLLMROUTER_ARTIFACT_ROOT"):
        raise SystemExit("EZLLMROUTER_ARTIFACT_ROOT is required")
    RUNS.mkdir(mode=0o700, parents=True, exist_ok=True)
    run = RUNS / sys.argv[1]
    if run.exists():
        raise SystemExit(
            "run ID already exists: "
            + str(run)
            + " (see its result.json or failure.json; select a new ID)"
        )
    run.mkdir(mode=0o700)
    current = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
    meta = {
        "kind": "DEV-08 frozen worker Responses build discriminator",
        "run_id": sys.argv[1],
        "source_commit": current,
        "dirty": bool(dirty),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "running_profile_restarted": False,
        "real_provider_calls": 0,
        "stages": [],
    }
    try:
        if dirty:
            raise RuntimeError(
                "source checkout is dirty; commit reviewed changes before target build"
            )
        artifact = Path(os.environ["EZLLMROUTER_ARTIFACT_ROOT"])
        if not (artifact / "ARTIFACT-CUSTODY.json").is_file():
            raise RuntimeError("declared frozen artifact custody missing")
        for name, action in (("prepare", "prepare"), ("build-images", "build-images")):
            code = command(
                name,
                [sys.executable, "-B", str(ROOT / "deploy/local/local_profile.py"), action],
                run,
            )
            meta["stages"].append({"name": name, "exit": code})
            if code:
                raise RuntimeError(name + " failed; see separately saved redacted command output")
        build = json.loads((ROOT / "deploy/local/.state/current-build.json").read_text())
        if build["commit"] != current or build["dirty"]:
            raise RuntimeError("prepared build does not match clean source commit")
        meta.update(
            status="PASS",
            fingerprint=build["fingerprint"],
            build_dir=build["build_dir"],
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        (run / "result.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
        print(json.dumps(meta, sort_keys=True))
    except Exception as exc:
        meta.update(
            status="FAIL",
            failure_type=type(exc).__name__,
            failure_stage=meta["stages"][-1]["name"] if meta["stages"] else "preflight",
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        (run / "failure.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
        raise SystemExit("DEV-08 target failed: " + str(exc) + "; evidence: " + str(run)) from exc


if __name__ == "__main__":
    main()
