#!/usr/bin/env python3
"""One-use owner Terminal upgrade for the DEV-07 researched catalogue."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys

import catalogue_import
import profile
from check import wait_health


RUNS = profile.STATE / "catalogue-runs"
RUN_ID = re.compile(r"catalogue-20261021-[0-9]{2,4}\Z")


def same_tree(left, right):
    def digest(root):
        return {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*")
            if p.is_file()
        }

    return digest(left) == digest(right)


def claim_run_id(run_id):
    if not RUN_ID.fullmatch(run_id):
        raise SystemExit("usage: catalogue_run.py catalogue-20261021-01")
    namespace = RUNS / run_id
    try:
        namespace.mkdir(mode=0o700, parents=True, exist_ok=False)
    except FileExistsError:
        raise SystemExit(
            f"run ID already exists: {run_id}; existing result location: "
            f"{namespace / 'result.json'}; no run was started"
        ) from None
    namespace.chmod(0o700)
    return namespace


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: catalogue_run.py catalogue-20261021-01")
    namespace = claim_run_id(sys.argv[1])
    result_path = namespace / "result.json"
    try:
        _, password = profile.secrets_on_disk()
        old = profile.current()
        old_env = profile.environment(old)
        profile.ensure_owner(old_env)
        before = profile.receiver_count(old_env)
        old_overview = catalogue_import.OperatorClient(password).get("/operator/v1/overview")
        if old_overview["build"]["fingerprint"] != old["fingerprint"]:
            raise RuntimeError("running profile differs from staged source")
        profile.backup_live_store(old_env)
        profile.command(
            "catalogue-prepare",
            [sys.executable, "-I", "-B", str(profile.LOCAL / "prepare.py")],
            env=os.environ.copy(),
        )
        build = profile.current()
        env = profile.environment(build)
        old_source, new_source = Path(old["build_dir"]), Path(build["build_dir"])
        for kind in ("receiver", "worker"):
            if not same_tree(old_source / kind, new_source / kind):
                raise RuntimeError(kind + " source changed; scoped image reuse unavailable")
            profile.command(
                "catalogue-tag-" + kind,
                [
                    *profile.DOCKER,
                    "tag",
                    old_env["EZLLMROUTER_" + kind.upper() + "_IMAGE"],
                    env["EZLLMROUTER_" + kind.upper() + "_IMAGE"],
                ],
                env,
            )
        profile.command(
            "catalogue-build-service",
            [
                *profile.DOCKER,
                "build",
                "--pull=false",
                "--network=none",
                "--build-arg",
                "PYTHON_IMAGE=" + profile.BASE,
                "-t",
                env["EZLLMROUTER_SERVICE_IMAGE"],
                "-f",
                str(new_source / "service/Dockerfile"),
                str(new_source / "service"),
            ],
            env,
        )
        profile.command("catalogue-stop", profile.compose_args("down", "--remove-orphans"), old_env)
        profile.command("catalogue-up", profile.compose_args("up", "-d", "--no-build"), env)
        profile.check_console_port(env)
        _, overview = wait_health(password)
        if overview["build"]["fingerprint"] != build["fingerprint"]:
            raise RuntimeError("running service is not the staged catalogue source")
        if profile.receiver_count(env) != before:
            raise RuntimeError("restart added a receiver arrival")
        profile.topology(env)
        if profile.receiver_count(env) != before:
            raise RuntimeError("topology controls added a receiver arrival")
        imported = catalogue_import.import_catalogue(
            catalogue_import.OperatorClient(password), catalogue_import.seed_data()
        )
        if profile.receiver_count(env) != before:
            raise RuntimeError("catalogue import added a receiver arrival")
        profile.command(
            "catalogue-readback-stop", profile.compose_args("down", "--remove-orphans"), env
        )
        profile.command(
            "catalogue-readback-up", profile.compose_args("up", "-d", "--no-build"), env
        )
        profile.check_console_port(env)
        _, readback_overview = wait_health(password)
        if readback_overview["build"]["fingerprint"] != build["fingerprint"]:
            raise RuntimeError("readback used unexpected build")
        client = catalogue_import.OperatorClient(password)
        models = client.get("/operator/v1/models")["items"]
        owner = client.get("/operator/v1/principals/owner.local")["principal"]
        if (
            sum(m.get("kind") == "real_catalogue" for m in models) != 12
            or owner["display_name"] != "Larry Mitchell"
            or profile.receiver_count(env) != before
        ):
            raise RuntimeError("persistent catalogue or no-new-send readback failed")
        result = {
            **imported,
            "receiver_before": before,
            "receiver_after": before,
            "running_source": {"commit": build["commit"], "fingerprint": build["fingerprint"]},
            "ordinary_restart_readback": "PASS",
        }
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(json.dumps(result, sort_keys=True))
    except Exception as exc:
        (namespace / "failure.json").write_text(
            json.dumps(
                {"status": "FAILED", "type": type(exc).__name__, "reason": str(exc)[:250]}, indent=2
            )
            + "\n"
        )
        raise


if __name__ == "__main__":
    main()
