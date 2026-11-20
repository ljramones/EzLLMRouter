#!/usr/bin/env python3
"""One-use, offline service update for DEV-07 administrator CRUD controls."""

from __future__ import annotations

if not __package__:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import json
import os
from pathlib import Path
import sys

from deploy.local.catalogue_import import OperatorClient
from deploy.local import local_profile as profile
from deploy.local.filesystem_support import same_tree, claim_run_id as claim_namespace
from deploy.local.check import wait_health


RUNS = profile.STATE / "crud-runs"
USAGE_KEYS = (
    "attempts",
    "intents_persisted",
    "final_requests_committed",
    "transmission_started_observed",
    "no_first_write_observed",
    "write_observation_unknown",
)


def claim_run_id(value):
    return claim_namespace(RUNS, value, "crud")


def database_counters(env):
    script = (
        "import json,sqlite3; "
        "db=sqlite3.connect('file:/data/store.sqlite?mode=ro',uri=True); "
        "names=('submissions','intents','guard_dispatches'); "
        "counts={name:db.execute('SELECT COUNT(*) FROM '+name).fetchone()[0] for name in names}; "
        "counts['caller_lookups']=db.execute('SELECT COALESCE(SUM(caller_lookups),0) FROM operator_launches').fetchone()[0]; "
        "print(json.dumps(counts,sort_keys=True))"
    )
    output, _ = profile.command(
        "crud-database-counters",
        profile.compose_args("exec", "-T", "service", "python", "-B", "-c", script),
        env,
    )
    return json.loads(output)


def snapshot(client, env):
    overview = client.get("/operator/v1/overview")
    usage = client.get("/operator/v1/usage")
    return {
        "build": overview["build"],
        "database": database_counters(env),
        "usage": {key: usage[key] for key in USAGE_KEYS},
        "receiver_arrivals": profile.receiver_count(env),
        "models": client.get("/operator/v1/models")["items"],
        "principals": client.get("/operator/v1/principals")["items"],
    }


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: crud_update.py crud-YYYYMMDD-01")
    run = claim_run_id(sys.argv[1])
    try:
        _, password = profile.secrets_on_disk()
        old = profile.current()
        old_env = profile.environment(old)
        profile.ensure_owner(old_env)
        before = snapshot(OperatorClient(password), old_env)
        if before["build"]["fingerprint"] != old["fingerprint"]:
            raise RuntimeError("running profile differs from staged source")
        profile.backup_live_store(old_env)
        profile.command(
            "crud-prepare",
            [sys.executable, "-I", "-B", str(profile.LOCAL / "prepare.py")],
            env=os.environ.copy(),
        )
        build = profile.current()
        if build["dirty"]:
            raise RuntimeError("uncommitted staged source")
        env = profile.environment(build)
        old_source, new_source = Path(old["build_dir"]), Path(build["build_dir"])
        for kind in ("receiver", "worker"):
            if not same_tree(old_source / kind, new_source / kind):
                raise RuntimeError(kind + " source changed; service-only update unavailable")
            profile.command(
                "crud-tag-" + kind,
                [
                    *profile.DOCKER,
                    "tag",
                    old_env["EZLLMROUTER_" + kind.upper() + "_IMAGE"],
                    env["EZLLMROUTER_" + kind.upper() + "_IMAGE"],
                ],
                env,
            )
        profile.command(
            "crud-build-service",
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
        profile.command("crud-stop", profile.compose_args("down", "--remove-orphans"), old_env)
        profile.command("crud-up", profile.compose_args("up", "-d", "--no-build"), env)
        profile.check_console_port(env)
        _, live = wait_health(password)
        if live["build"]["fingerprint"] != build["fingerprint"]:
            raise RuntimeError("unexpected running service source")
        after = snapshot(OperatorClient(password), env)
        if any(
            before[key] != after[key]
            for key in ("database", "usage", "receiver_arrivals", "models", "principals")
        ):
            raise RuntimeError("source update changed registry, accounting or model traffic")
        result = {
            "status": "PASS",
            "source_commit": build["commit"],
            "source_fingerprint": build["fingerprint"],
            "database_before_after": before["database"],
            "usage_before_after": before["usage"],
            "receiver_arrivals_before_after": before["receiver_arrivals"],
            "model_records_preserved": len(before["models"]),
            "principal_records_preserved": len(before["principals"]),
        }
        (run / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(json.dumps(result, sort_keys=True))
    except Exception as exc:
        (run / "failure.json").write_text(
            json.dumps(
                {"status": "FAILED", "type": type(exc).__name__, "reason": str(exc)[:250]}, indent=2
            )
            + "\n"
        )
        raise


if __name__ == "__main__":
    main()
