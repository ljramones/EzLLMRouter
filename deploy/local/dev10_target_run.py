#!/usr/bin/env python3
"""One-use isolated DEV-10 allowance target proof; never starts the live profile."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import profile as local_profile


ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "deploy/local/.state/dev10-target-runs"
DOCKER = local_profile.DOCKER


def absent_resource(error: str, resource: str) -> bool:
    """Accept Docker's absent-object wording, but never an access/daemon error."""
    lowered = error.casefold()
    return resource.casefold() in lowered and any(phrase in lowered for phrase in
        ("no such volume", "no such object", "no such container"))


def command(name, argv, run, *, timeout=180, allowed=(0,)):
    started = time.time()
    try:
        proc = subprocess.run(argv, cwd=ROOT, env=os.environ.copy(),
                              capture_output=True, text=True, timeout=timeout)
        out, err, code = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        code = 124
    (run / (name + ".stdout.txt")).write_text(local_profile.redact(out))
    (run / (name + ".stderr.txt")).write_text(local_profile.redact(err))
    (run / (name + ".exit.txt")).write_text(str(code) + "\n")
    if name == "build-images":
        records = ROOT / "deploy/local/.state/commands"
        for stage in ("build-receiver", "build-worker", "build-service"):
            for extension in ("stdout", "stderr", "exit"):
                source = records / (stage + "." + extension)
                if source.is_file() and source.stat().st_mtime >= started - 1:
                    (run / (stage + "." + extension + ".txt")).write_text(
                        local_profile.redact(source.read_text()))
    print("DEV-10 target: " + name + " exited " + str(code), flush=True)
    if code not in allowed:
        tail = "\n".join(local_profile.redact(err).splitlines()[-12:])[:1500]
        if tail:
            print(tail, file=sys.stderr)
        raise RuntimeError(name + " failed; inspect separately saved redacted output")
    return out.strip(), code


def main():
    if len(sys.argv) != 2 or not re.fullmatch(r"dev10-target-[0-9]{8}-[0-9]{2}", sys.argv[1]):
        raise SystemExit("usage: dev10_target_run.py dev10-target-YYYYMMDD-NN")
    if not os.environ.get("DURANKI_ARTIFACT_ROOT"):
        raise SystemExit("DURANKI_ARTIFACT_ROOT is required")
    RUNS.mkdir(mode=0o700, parents=True, exist_ok=True)
    run = RUNS / sys.argv[1]
    if run.exists():
        raise SystemExit("run ID already exists: " + str(run) +
                         " (see result.json or failure.json; choose a fresh ID)")
    run.mkdir(mode=0o700)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    meta = {"kind": "DEV-10 isolated installed-client controlled HTTPS target",
            "run_id": sys.argv[1], "source_commit": commit, "dirty": dirty,
            "started_at": datetime.now(timezone.utc).isoformat(), "stages": [],
            "persistent_profile_restarted": False, "real_provider_calls": 0}
    suffix = sys.argv[1].replace("_", "-")
    worker, service, volume = ("duranki-" + suffix + "-worker",
                               "duranki-" + suffix + "-service",
                               "duranki-" + suffix + "-link")
    created_volume = False
    started_worker = False
    started_service = False
    try:
        if dirty:
            raise RuntimeError("source checkout is dirty; commit reviewed source first")
        if not (Path(os.environ["DURANKI_ARTIFACT_ROOT"]) / "ARTIFACT-CUSTODY.json").is_file():
            raise RuntimeError("declared frozen artifact custody missing")
        for kind, resource in (("volume", volume), ("container", worker), ("container", service)):
            argv = ([*DOCKER, "volume", "inspect", resource] if kind == "volume" else
                    [*DOCKER, "container", "inspect", resource])
            _, code = command("collision-" + kind + "-" + resource, argv, run, allowed=(0, 1))
            if code == 0:
                raise RuntimeError("preexisting Docker resource collision: " + resource)
            error = (run / ("collision-" + kind + "-" + resource + ".stderr.txt")).read_text()
            if not absent_resource(error, resource):
                raise RuntimeError("Docker inspect failed for a reason other than resource absence")
        for stage in ("prepare", "build-images"):
            _, code = command(stage, [sys.executable, "-B", str(ROOT / "deploy/local/profile.py"), stage],
                              run, timeout=900)
            meta["stages"].append({"name": stage, "exit": code})
        build = local_profile.current()
        if build["commit"] != commit or build["dirty"]:
            raise RuntimeError("staged build does not match clean source")
        env = local_profile.environment(build)
        command("create-link", [*DOCKER, "volume", "create", volume], run)
        created_volume = True
        command("start-worker", [*DOCKER, "run", "-d", "--pull=never", "--name", worker,
            "--network=none", "--read-only", "--user", "10001:10001",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=32m", "--cap-drop=ALL",
            "--security-opt", "no-new-privileges:true", "-v", volume + ":/link",
            env["DURANKI_WORKER_IMAGE"]], run)
        started_worker = True
        command("worker-topology", [*DOCKER, "inspect", "--format",
            "{{.HostConfig.NetworkMode}}", worker], run)
        if (run / "worker-topology.stdout.txt").read_text().strip() != "none":
            raise RuntimeError("worker network mode differs from none")
        output, _ = command("installed-client-proof", [*DOCKER, "run", "--rm", "--pull=never",
            "--name", service, "--network=none", "--read-only", "--user", "10001:10001",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=32m", "--cap-drop=ALL",
            "--security-opt", "no-new-privileges:true", "-v", volume + ":/link",
            env["DURANKI_SERVICE_IMAGE"], "python", "-B",
            "/app/gateway/dev10_target.py"], run, timeout=300)
        result = json.loads(output)
        if result.get("status") != "PASS" or result.get("receiver_arrivals") != 3 or \
                result.get("first_byte_sends") != 3 or result.get("guard_commits") != 3 or \
                result.get("real_provider_calls") != 0:
            raise RuntimeError("integrated receipt is incomplete")
        source = Path(build["build_dir"]) / "dev09_js"
        js_image = "duranki-dev10-jsactor:" + build["fingerprint"][:16]
        command("build-installed-commonjs", [*DOCKER, "build", "--pull=false", "--network=none",
            "--build-arg", "NODE_IMAGE=" + local_profile.NODE, "-t", js_image,
            "-f", str(source / "Dockerfile"), str(source)], run, timeout=600)
        command("start-commonjs-service", [*DOCKER, "run", "-d", "--pull=never", "--name", service,
            "--network=none", "--read-only", "--user", "10001:10001",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=32m", "--cap-drop=ALL",
            "--security-opt", "no-new-privileges:true", "-v", volume + ":/link",
            env["DURANKI_SERVICE_IMAGE"], "python", "-B", "/app/gateway/dev10_target.py",
            "--commonjs"], run)
        started_service = True
        command("installed-commonjs-proof", [*DOCKER, "run", "--rm", "--pull=never",
            "--network", "container:" + service, "--read-only",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=16m", "--cap-drop=ALL",
            "--security-opt", "no-new-privileges:true", "-v", volume + ":/link",
            js_image, "node", "/app/consumer/dev10_js_actor.cjs"], run, timeout=90)
        exit_text, _ = command("commonjs-service-wait", [*DOCKER, "wait", service], run, timeout=90)
        if exit_text != "0":
            raise RuntimeError("CommonJS service failed; inspect its saved logs")
        js_text, _ = command("commonjs-service-logs", [*DOCKER, "logs", service], run)
        js_result = json.loads(js_text)
        if (js_result.get("status") != "PASS" or js_result.get("receiver_arrivals") != 1 or
                js_result.get("first_byte_sends") != 1 or js_result.get("guard_commits") != 1 or
                js_result.get("prior_worker_attempts") != result.get("worker_attempts_after") or
                js_result.get("worker_attempts_after") != result.get("worker_attempts_after") + 1 or
                not js_result["cases"]["commonjs"]["installed_commonjs"]):
            raise RuntimeError("CommonJS selected-path receipt is incomplete")
        meta.update(status="PASS", fingerprint=build["fingerprint"], result=result,
                    commonjs_result=js_result, controlled_receiver_arrivals_total=4,
                    completed_at=datetime.now(timezone.utc).isoformat())
        (run / "result.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
        print(json.dumps(meta, sort_keys=True))
    except Exception as exc:
        meta.update(status="FAIL", failure_type=type(exc).__name__,
                    completed_at=datetime.now(timezone.utc).isoformat())
        (run / "failure.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
        print("DEV-10 target failed: " + str(exc) + "; evidence: " + str(run), file=sys.stderr)
        raise SystemExit(1)
    finally:
        if started_service:
            try:
                command("commonjs-service-final-logs", [*DOCKER, "logs", service], run,
                        allowed=(0, 1))
                command("remove-commonjs-service", [*DOCKER, "rm", "-f", service], run)
            except Exception:
                pass
        if started_worker:
            try:
                command("worker-logs", [*DOCKER, "logs", "--tail", "40", worker], run, allowed=(0, 1))
            except Exception:
                pass
            command("remove-worker", [*DOCKER, "rm", "-f", worker], run)
        if created_volume:
            command("remove-link", [*DOCKER, "volume", "rm", volume], run)


if __name__ == "__main__":
    main()
