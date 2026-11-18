#!/usr/bin/env python3
"""One-use, service-only owner update for DEV-07 operator projections and views."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys

from catalogue_import import OperatorClient
import profile
from check import wait_health


RUNS = profile.STATE / "usage-runs"
RUN_ID = re.compile(r"usage-20261021-[0-9]{2,4}\Z")


def same_tree(left, right):
    def inventory(root):
        return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in root.rglob("*") if path.is_file()}
    return inventory(left) == inventory(right)


def claim_run_id(value):
    if not RUN_ID.fullmatch(value):
        raise SystemExit("usage: usage_update.py usage-20261021-01")
    run = RUNS / value
    try:
        run.mkdir(mode=0o700, parents=True, exist_ok=False)
    except FileExistsError:
        raise SystemExit(f"run ID already exists: {value}; existing result location: "
                         f"{run / 'result.json'}; no update was started") from None
    run.chmod(0o700)
    return run


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: usage_update.py usage-20261021-01")
    run = claim_run_id(sys.argv[1])
    try:
        _, password = profile.secrets_on_disk()
        old = profile.current()
        old_env = profile.environment(old)
        profile.ensure_owner(old_env)
        client = OperatorClient(password)
        overview = client.get("/operator/v1/overview")
        if overview["build"]["fingerprint"] != old["fingerprint"]:
            raise RuntimeError("running profile differs from staged source")
        before_receiver = profile.receiver_count(old_env)
        before_submissions = overview["counts"]["submissions"]
        before_receipts = client.get("/operator/v1/usage")["dispatched"]
        profile.backup_live_store(old_env)
        profile.command("usage-prepare", [sys.executable, "-I", "-B",
            str(profile.LOCAL / "prepare.py")], env=os.environ.copy())
        build = profile.current()
        env = profile.environment(build)
        old_source, new_source = Path(old["build_dir"]), Path(build["build_dir"])
        for kind in ("receiver", "worker"):
            if not same_tree(old_source / kind, new_source / kind):
                raise RuntimeError(kind + " source changed; service-only update unavailable")
            profile.command("usage-tag-" + kind,
                [*profile.DOCKER, "tag", old_env["DURANKI_" + kind.upper() + "_IMAGE"],
                 env["DURANKI_" + kind.upper() + "_IMAGE"]], env)
        profile.command("usage-build-service", [*profile.DOCKER, "build", "--pull=false",
            "--network=none", "--build-arg", "PYTHON_IMAGE=" + profile.BASE,
            "-t", env["DURANKI_SERVICE_IMAGE"], "-f", str(new_source / "service/Dockerfile"),
            str(new_source / "service")], env)
        profile.command("usage-stop", profile.compose_args("down", "--remove-orphans"), old_env)
        profile.command("usage-up", profile.compose_args("up", "-d", "--no-build"), env)
        profile.check_console_port(env)
        _, live = wait_health(password)
        if live["build"]["fingerprint"] != build["fingerprint"]:
            raise RuntimeError("unexpected running service source")
        client = OperatorClient(password)
        usage = client.get("/operator/v1/usage")
        models = client.get("/operator/v1/models")["items"]
        owner = client.get("/operator/v1/principals/owner.local")["principal"]
        after_receiver = profile.receiver_count(env)
        if (live["counts"]["submissions"] != before_submissions or
                usage["attempts"] != before_submissions or
                usage["final_requests_committed"] != before_receipts or
                after_receiver != before_receiver or
                sum(model.get("kind") == "real_catalogue" and
                    model.get("readiness") == "not_connected" for model in models) != 12 or
                owner["display_name"] != "Larry Mitchell"):
            raise RuntimeError("no-new-send or registry readback failed")
        result = {"status": "PASS", "source_commit": build["commit"],
                  "source_fingerprint": build["fingerprint"],
                  "submissions_before": before_submissions, "submissions_after": usage["attempts"],
                  "final_requests_committed": usage["final_requests_committed"],
                  "first_write_observed": usage["transmission_started_observed"],
                  "no_first_write_observed": usage["no_first_write_observed"],
                  "write_observation_unknown": usage["write_observation_unknown"],
                  "receiver_before": before_receiver, "receiver_after": after_receiver,
                  "catalogue_disconnected": 12, "owner_name": "Larry Mitchell"}
        (run / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(json.dumps(result, sort_keys=True))
    except Exception as exc:
        (run / "failure.json").write_text(json.dumps({"status": "FAILED",
            "type": type(exc).__name__, "reason": str(exc)[:250]}, indent=2) + "\n")
        raise


if __name__ == "__main__":
    main()
