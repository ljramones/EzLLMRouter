#!/usr/bin/env python3
"""One-use owner Terminal migration and controlled installed-client proof."""

from __future__ import annotations

if not __package__:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys

from deploy.local import local_profile as profile
from deploy.local import prepare
from deploy.local.command_support import capture, record
from deploy.local.check import wait_health
from deploy.local.dev08_profile_upgrade import running_build


RUNS = profile.STATE / "dev09-profile-runs"
RUN_ID = re.compile(r"dev09-profile-[0-9]{8}-[0-9]{2,4}\Z")


def claim(run_id):
    if not RUN_ID.fullmatch(run_id):
        raise SystemExit("usage: dev09_profile_run.py dev09-profile-YYYYMMDD-NN")
    path = RUNS / run_id
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=False)
    except FileExistsError:
        raise SystemExit(
            f"run ID already exists: {run_id}; existing result location: "
            f"{path / 'result.json'}; no run was started"
        ) from None
    return path


def save(path, name, value):
    (path / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def command(path, name, argv, env, *, payload=None, timeout=180):
    print("DEV-09 profile: " + name + "…", flush=True)

    def redact_output(value):
        value = profile.redact(value)
        token = (payload or {}).get("token")
        return value.replace(token, "[REDACTED]") if isinstance(token, str) and token else value

    result = record(
        path,
        name,
        capture(
            argv,
            cwd=profile.ROOT,
            env=env,
            payload=json.dumps(payload) if payload is not None else None,
            timeout=timeout,
        ),
        redact_output,
    )
    stdout, stderr = result.stdout, result.stderr
    print("DEV-09 profile: " + name + " exited " + str(result.returncode), flush=True)
    if result.returncode:
        raise RuntimeError(name + " failed; redacted tail: " + stderr[-1200:])
    return stdout.strip()


def receiver_count(path, name, env):
    code = (
        "import pathlib; p=pathlib.Path('/data/arrivals.jsonl'); "
        "print(len(p.read_text().splitlines()) if p.exists() else 0)"
    )
    return int(
        command(
            path, name, profile.compose_args("exec", "-T", "receiver", "python", "-c", code), env
        )
    )


def snapshot(path, name, password, env):
    client, overview = wait_health(password, seconds=12)
    return client, {
        "commit": overview["build"]["commit"],
        "fingerprint": overview["build"]["fingerprint"],
        "submissions": overview["counts"]["submissions"],
        "receiver_arrivals": receiver_count(path, name + "-receiver", env),
        "connections": len(client.call("GET", "/operator/v1/connections")["items"]),
    }


def mutate(client, run_id, number, action, subject, expected_revision, data):
    return client.call(
        "POST",
        "/operator/v1/registry",
        {
            "operation_id": "op." + run_id + "." + str(number),
            "action": action,
            "subject": subject,
            "expected_revision": expected_revision,
            "data": data,
        },
    )


def actor(path, name, argv, env, *, token, rows, outcome=None, denied=False):
    payload = {"base_url": "http://127.0.0.1:8773", "token": token, "rows": rows}
    if outcome:
        payload["outcome"] = outcome
        payload["expect_outcome_authority"] = not denied
    return json.loads(command(path, name, argv, env, payload=payload))


def exercise(path, run_id, client, env, before):
    # Every added identity is explicitly synthetic and local to this one run.
    suffix = run_id.replace("-", ".")
    users = ["user.synthetic.alpha." + suffix, "user.synthetic.beta." + suffix]
    agent = "agent.synthetic." + suffix
    tokens = {}
    _provision_exercise_users_and_agent(agent, client, run_id, suffix, tokens, users)

    auto, beta, child, netns, py, rejected, results, service_token = (
        _exercise_installed_python_attribution(agent, env, path, suffix, tokens, users)
    )
    if not re.fullmatch(r"[0-9a-f]{12,64}", netns):
        raise RuntimeError("one owned netns container required")
    js_image = "ezllmrouter-dev09-jsactor:" + env["EZLLMROUTER_SERVICE_IMAGE"].split(":")[-1]
    js = [
        *profile.DOCKER,
        "run",
        "--rm",
        "--pull=never",
        "--network",
        "container:" + netns,
        "--user",
        "node",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=8m",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "-i",
        js_image,
    ]
    results.append(
        actor(
            path,
            "installed-commonjs-nested-and-users",
            js,
            env,
            token=service_token,
            rows=[child, beta, auto],
        )
    )
    if [len(item["runs"]) for item in results] != [1, 1, 3] or any(
        run["state"] != "delivered" for item in results for run in item["runs"]
    ):
        raise RuntimeError("installed-client target delivery mismatch")
    mutate(
        client,
        run_id,
        50,
        "set_outcome_authority",
        "svc.demo",
        0,
        {"status": "active", "task_classes": ["class.demo"]},
    )
    accepted = {
        **rejected,
        "event_id": "event." + suffix + ".accepted",
        "evidence_ref": "evidence.synthetic.accepted",
    }
    receipt_py = actor(
        path, "installed-python-outcome", py, env, token=service_token, rows=[], outcome=accepted
    )
    revised = {
        **accepted,
        "event_id": "event." + suffix + ".revised",
        "subject_revision": 2,
        "verdict": "rejected",
        "evidence_ref": "evidence.synthetic.revised",
    }
    receipt_js = actor(
        path, "installed-commonjs-outcome", js, env, token=service_token, rows=[], outcome=revised
    )
    if [receipt_py["outcome"]["subject_revision"], receipt_js["outcome"]["subject_revision"]] != [
        1,
        2,
    ]:
        raise RuntimeError("outcome revision/read receipts mismatch")
    ids = [run["submission_id"] for item in results for run in item["runs"]]
    details = [client.call("GET", "/operator/v1/activity/" + sid) for sid in ids]
    if any(
        item["submission_state"] != "completed" or item["dispatch_receipt"]["present"] is not True
        for item in details
    ):
        raise RuntimeError("target completed intent or trusted-sender receipt missing")
    after = snapshot(path, "after-exercise", profile.secrets_on_disk()[1], env)[1]
    if (
        after["submissions"] - before["submissions"] != 5
        or after["receiver_arrivals"] - before["receiver_arrivals"] != 5
    ):
        raise RuntimeError("target submissions and independent receiver arrivals disagree")
    query = "/operator/v1/usage-costs?limit=50"
    report = client.call("GET", query)
    target = [
        item
        for item in report["attempts"]
        if item.get("run_id", "").startswith("run." + suffix + ".")
    ]
    if (
        len(target) != 5
        or {item["agent_id"] for item in target} != {agent, "__direct_human__"}
        or {item["initiating_user_id"] for item in target} != {*users, "__autonomous__"}
    ):
        raise RuntimeError("trusted run attribution absent from operator projection")
    return {
        "before": before,
        "after": after,
        "submissions": len(ids),
        "receiver_arrivals_added": 5,
        "matched_attributed_attempts": len(target),
        "outcome_revisions": [1, 2],
        "real_provider_calls": 0,
        "synthetic_cost_state": "unknown",
        "installed_clients": {
            "python": prepare.PYTHON_CLIENT["version"],
            "javascript": prepare.JS_CLIENT["version"],
        },
    }


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: dev09_profile_run.py dev09-profile-YYYYMMDD-NN")
    run_id = sys.argv[1]
    path = claim(run_id)
    stages = []
    try:
        _, password = profile.secrets_on_disk()
        old = running_build(password)
        old_env = profile.environment(old)
        profile.ensure_owner(old_env)
        _, before = snapshot(path, "before", password, old_env)
        if before["fingerprint"] != old["fingerprint"]:
            raise RuntimeError("running profile source mismatch")
        stages.append("running-identity-and-counts")
        backups = set((profile.STATE / "backups").glob("dev07-pre-migration-*.sqlite"))
        profile.backup_live_store(old_env)
        new_backups = (
            set((profile.STATE / "backups").glob("dev07-pre-migration-*.sqlite")) - backups
        )
        if len(new_backups) != 1:
            raise RuntimeError("exactly one new consistent SQLite backup required")
        backup = new_backups.pop()
        stages.append("online-consistent-backup")
        command(
            path,
            "prepare",
            [sys.executable, "-I", "-B", str(profile.LOCAL / "prepare.py")],
            os.environ.copy(),
        )
        build = profile.current()
        if (
            build["dirty"]
            or build["commit"] == old["commit"]
            and build["fingerprint"] == old["fingerprint"]
        ):
            raise RuntimeError("clean changed DEV-09 source required")
        env = profile.environment(build)
        for kind in ("RECEIVER", "WORKER"):
            env["EZLLMROUTER_" + kind + "_IMAGE"] = old_env["EZLLMROUTER_" + kind + "_IMAGE"]
        stages.append("prepare-clean-source-and-reuse-unchanged-images")
        source = Path(build["build_dir"])
        service_image = env["EZLLMROUTER_SERVICE_IMAGE"]
        command(
            path,
            "build-service",
            [
                *profile.DOCKER,
                "build",
                "--pull=false",
                "--network=none",
                "--build-arg",
                "PYTHON_IMAGE=" + profile.BASE,
                "-t",
                service_image,
                "-f",
                str(source / "service/Dockerfile"),
                str(source / "service"),
            ],
            env,
            timeout=900,
        )
        js_image = "ezllmrouter-dev09-jsactor:" + build["fingerprint"][:16]
        command(
            path,
            "build-installed-commonjs",
            [
                *profile.DOCKER,
                "build",
                "--pull=false",
                "--network=none",
                "--build-arg",
                "NODE_IMAGE=" + profile.NODE,
                "-t",
                js_image,
                "-f",
                str(source / "dev09_js/Dockerfile"),
                str(source / "dev09_js"),
            ],
            env,
            timeout=600,
        )
        stages.append("offline-frozen-build-and-target-preflight")
        migrated = json.loads(
            command(
                path,
                "copied-backup-migration",
                [
                    *profile.DOCKER,
                    "run",
                    "--rm",
                    "--pull=never",
                    "--network=none",
                    "--read-only",
                    "--tmpfs",
                    "/tmp:rw,nosuid,nodev,size=64m",
                    "--user",
                    str(os.getuid()) + ":" + str(os.getgid()),
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges:true",
                    "--mount",
                    "type=bind,src=" + str(backup) + ",dst=/backup/store.sqlite,readonly",
                    *profile.fixture_mounts(build),
                    service_image,
                    "python",
                    "-B",
                    "/app/gateway/dev09_migration_check.py",
                    "/backup/store.sqlite",
                ],
                env,
            )
        )
        if (
            migrated["status"] != "PASS"
            or migrated["historical_table_counts"]["submissions"] != before["submissions"]
        ):
            raise RuntimeError("disposable target migration failed historical count check")
        stages.append("target-migration-on-copied-backup")
        command(path, "profile-stop", profile.compose_args("down", "--remove-orphans"), old_env)
        stages.append("profile-stopped-with-volumes-preserved")
        command(path, "profile-up", profile.compose_args("up", "-d", "--no-build"), env)
        profile.check_console_port(env)
        client, restarted = snapshot(path, "after-restart", password, env)
        if restarted["fingerprint"] != build["fingerprint"] or any(
            restarted[key] != before[key]
            for key in ("submissions", "receiver_arrivals", "connections")
        ):
            raise RuntimeError("persistent profile restart/readback changed history")
        profile.topology(env)
        stages.append("restart-readback-and-topology")
        proof = exercise(path, run_id, client, env, restarted)
        stages.append("installed-clients-trusted-sender-and-report")
        result = {
            "kind": "DEV-09 persistent profile controlled attribution proof",
            "status": "PASS",
            "run_id": run_id,
            "source_commit": build["commit"],
            "fingerprint": build["fingerprint"],
            "started_source": before,
            "migration": migrated,
            "proof": proof,
            "stages": stages,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "backup_path": str(backup),
            "real_provider_calls": 0,
        }
        save(path, "result.json", result)
        print(json.dumps(result, sort_keys=True))
    except Exception as exc:
        save(
            path,
            "failure.json",
            {
                "status": "FAILED",
                "run_id": run_id,
                "stages_completed": stages,
                "error_type": type(exc).__name__,
                "message": profile.redact(str(exc))[:1200],
            },
        )
        print(
            "DEV-09 profile failed: " + type(exc).__name__ + "; evidence: " + str(path),
            file=sys.stderr,
        )
        raise SystemExit(1) from None


def _provision_exercise_users_and_agent(agent, client, run_id, suffix, tokens, users):
    for n, user in enumerate(users):
        mutate(
            client,
            run_id,
            10 + n * 10,
            "create_principal",
            user,
            0,
            {
                "display_name": "Synthetic DEV-09 user " + str(n + 1),
                "kind": "human",
                "owner": "team.demo",
            },
        )
        issued = client.call(
            "POST",
            "/operator/v1/provision",
            {
                "operation_id": "op." + run_id + ".credential." + str(n),
                "principal_id": user,
                "expected_revision": 1,
            },
        )
        tokens[user] = issued["one_time_credential"]
        mutate(
            client,
            run_id,
            11 + n * 10,
            "principal_state",
            user,
            2,
            {"status": "active", "reason": "Controlled DEV-09 proof"},
        )
        mutate(
            client,
            run_id,
            12 + n * 10,
            "set_grant",
            user,
            0,
            {
                "configuration_ref": "cfg.demo",
                "status": "active",
                "purposes": ["execution"],
                "task_classes": ["class.demo"],
            },
        )
    mutate(
        client,
        run_id,
        40,
        "register_agent",
        agent,
        0,
        {"display_name": "Synthetic DEV-09 shared agent", "owner": "team.demo", "versions": ["v1"]},
    )
    for n, user in enumerate((None, *users)):
        data = {
            "caller_principal_id": "svc.demo",
            "agent_id": agent,
            "charging_owner_id": "team.demo",
            "task_classes": ["class.demo"],
            "status": "active",
        }
        if user:
            data["initiating_user_id"] = user
        mutate(
            client,
            run_id,
            41 + n,
            "set_agent_permission",
            "permission.synthetic." + suffix + "." + str(n),
            0,
            data,
        )


def _exercise_installed_python_attribution(agent, env, path, suffix, tokens, users):
    request = json.loads((profile.ROOT / "tests/development_slice/request.json").read_text())

    def row(name, mode, **fields):
        req = deepcopy(request)
        req["execution_generation"] = "gen." + suffix + "." + name
        req["step_id"] = "step." + suffix + "." + name
        if req["requested_configuration_ref"] != "cfg.demo":
            raise RuntimeError("controlled target request no longer selects synthetic cfg.demo")
        run = {
            "version": "1",
            "run_id": "run." + suffix + "." + name,
            "task_id": req["task_id"],
            "task_class": req["task_class"],
            "evaluation_ref": "rubric.synthetic.v1",
            "mode": mode,
            **fields,
        }
        return {"run": run, "request": req}

    direct = row("direct", "direct_human")
    alpha = row(
        "alpha",
        "user_delegated_agent",
        agent_id=agent,
        agent_version="v1",
        initiating_user_id=users[0],
    )
    child = row(
        "child",
        "nested_agent",
        agent_id=agent,
        agent_version="v1",
        parent_run_id=alpha["run"]["run_id"],
    )
    beta = row(
        "beta",
        "user_delegated_agent",
        agent_id=agent,
        agent_version="v1",
        initiating_user_id=users[1],
    )
    auto = row("auto", "autonomous_agent", agent_id=agent, agent_version="v1")
    service_token = profile.secrets_on_disk()[0]["service_token"]
    py = profile.compose_args(
        "exec",
        "-T",
        "service",
        "python",
        "-B",
        "-c",
        (Path(profile.current()["build_dir"]) / "service/local/dev09_python_actor.py").read_text(),
    )
    results = [
        actor(path, "installed-python-direct", py, env, token=tokens[users[0]], rows=[direct])
    ]
    rejected = {
        "version": "1",
        "event_id": "event." + suffix + ".denied",
        "run_id": alpha["run"]["run_id"],
        "kind": "task_outcome",
        "subject_revision": 1,
        "verdict": "accepted",
        "evaluator_version": "rubric.synthetic.v1",
        "evidence_ref": "evidence.synthetic",
    }
    results.append(
        actor(
            path,
            "installed-python-delegated",
            py,
            env,
            token=service_token,
            rows=[alpha],
            outcome=rejected,
            denied=True,
        )
    )
    netns = command(path, "netns-container-id", profile.compose_args("ps", "-q", "netns"), env)
    return auto, beta, child, netns, py, rejected, results, service_token


if __name__ == "__main__":
    main()
