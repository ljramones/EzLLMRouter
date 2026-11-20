#!/usr/bin/env python3
"""Persistent local synthetic profile. Docker runs only in the owner Terminal."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone

from check import exercise, readback, wait_health


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
from ezllmrouter_server.private_files import read_private, write_private

LOCAL = ROOT / "deploy/local"
STATE = LOCAL / ".state"
COMPOSE = LOCAL / "compose.yaml"
PROJECT = "ezllmrouter-dev06-local"
BASE = "docker.io/library/python@sha256:739ba32ae445e8d58f3d90feb85f83bebc8346f8dd280fa1eb5848f4ff1ed163"
NODE = (
    "docker.io/library/node@sha256:be8204d4bd327363357f532187b752ff62759c31bedf98e9e18fc08c9cbd605c"
)
DOCKER = ["docker", "--context", "desktop-linux"]


def secrets_on_disk():
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    if STATE.is_symlink():
        raise RuntimeError("local secret directory must not be a symlink")
    STATE.chmod(0o700)
    credentials = STATE / "credentials.json"
    password = STATE / "operator-password"
    bundle = STATE / "profile-secrets.json"
    # Adopt existing profile credentials without rotating them. Repair the old
    # 0644 files before reading; reject links, special files and foreign owners.
    for path in (bundle, credentials, password):
        if path.is_symlink():
            raise RuntimeError("local credentials must not be symlinks")
        if path.exists():
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
                    raise RuntimeError("local credentials must be owned regular files")
                os.fchmod(descriptor, 0o600)
            finally:
                os.close(descriptor)
    if not bundle.exists() and credentials.exists() != password.exists():
        raise RuntimeError(
            "partial local credentials; inspect .state without overwriting either file"
        )
    if bundle.exists():
        saved = json.loads(read_private(bundle))
        data, value = saved["credentials"], saved["operator_password"]
    elif credentials.exists():
        data = json.loads(read_private(credentials))
        value = read_private(password).decode("ascii").strip()
    else:
        data = {
            "service_token": secrets.token_urlsafe(36),
            "synthetic_provider_key": "sk-" + secrets.token_hex(32),
        }
        value = secrets.token_urlsafe(36)
    if (
        set(data) != {"service_token", "synthetic_provider_key"}
        or not all(isinstance(item, str) for item in data.values())
        or not isinstance(value, str)
        or len(data["service_token"]) < 32
        or not data["synthetic_provider_key"].startswith("sk-")
        or len(value) < 32
    ):
        raise RuntimeError("invalid local credential files")
    # Publish one canonical bundle first: interruption between the two derived
    # files can then resume with exactly the same credentials.
    if not bundle.exists():
        try:
            write_private(
                bundle,
                json.dumps({"credentials": data, "operator_password": value}).encode("ascii"),
            )
        except FileExistsError:
            return secrets_on_disk()
    for path, content in (
        (credentials, (json.dumps(data) + "\n").encode("ascii")),
        (password, (value + "\n").encode("ascii")),
    ):
        if path.exists():
            existing = read_private(path)
            matches = (
                json.loads(existing) == data
                if path == credentials
                else existing.decode("ascii").strip() == value
            )
            if not matches:
                raise RuntimeError("local credential files disagree with the canonical bundle")
        else:
            write_private(path, content)
    return data, value


def redact(value):
    bundle = STATE / "profile-secrets.json"
    if bundle.is_file() and not bundle.is_symlink():
        try:
            saved = json.loads(read_private(bundle))
            for secret in (*saved["credentials"].values(), saved["operator_password"]):
                if isinstance(secret, str) and secret:
                    value = value.replace(secret, "[REDACTED]")
        except (OSError, ValueError, KeyError, TypeError):
            pass
    for path in (STATE / "credentials.json", STATE / "operator-password"):
        if not path.exists():
            continue
        try:
            values = (
                json.loads(path.read_text()).values()
                if path.name.endswith(".json")
                else (path.read_text().strip(),)
            )
        except (OSError, ValueError, TypeError):
            values = ()
        for secret in values:
            if secret:
                value = value.replace(secret, "[REDACTED]")
    return value


def command(name, argv, env=None, allowed=(0,), input_data=None):
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    records = STATE / "commands"
    records.mkdir(exist_ok=True)
    print("Local profile: " + name + "…", flush=True)
    result = subprocess.run(
        argv, cwd=ROOT, env=env, capture_output=True, text=True, input=input_data, timeout=900
    )
    stdout, stderr = redact(result.stdout), redact(result.stderr)
    (records / (name + ".stdout")).write_text(stdout)
    (records / (name + ".stderr")).write_text(stderr)
    (records / (name + ".exit")).write_text(str(result.returncode) + "\n")
    print("Local profile: " + name + " exited " + str(result.returncode), flush=True)
    if result.returncode not in allowed:
        print(name + " failed (exit " + str(result.returncode) + ")", file=sys.stderr)
        print("\n".join(stderr.splitlines()[-12:])[:1500], file=sys.stderr)
        raise RuntimeError(name + " failed")
    return stdout.strip(), result.returncode


def current():
    path = STATE / "current-build.json"
    if not path.is_file():
        raise RuntimeError("profile not prepared")
    value = json.loads(path.read_text())
    if not Path(value["build_dir"]).is_dir():
        raise RuntimeError("staged build directory missing")
    return value


def environment(build):
    suffix = build["fingerprint"][:16]
    return dict(
        os.environ,
        EZLLMROUTER_PYTHON_IMAGE=BASE,
        EZLLMROUTER_INGRESS_SCRIPT=str(Path(build["build_dir"]) / "ingress/console_ingress.py"),
        EZLLMROUTER_RECEIVER_IMAGE="ezllmrouter-dev06-receiver:" + suffix,
        EZLLMROUTER_WORKER_IMAGE="ezllmrouter-dev06-worker:" + suffix,
        EZLLMROUTER_SERVICE_IMAGE="ezllmrouter-dev06-service:" + suffix,
        EZLLMROUTER_DEV07_PYACTOR_IMAGE="ezllmrouter-dev07-pyactor:" + suffix,
        EZLLMROUTER_DEV07_JSACTOR_IMAGE="ezllmrouter-dev07-jsactor:" + suffix,
    )


def compose_args(*args):
    return [*DOCKER, "compose", "-f", str(COMPOSE), *args]


def ensure_owner(env):
    marker = STATE / "PROFILE-OWNER.json"
    if marker.exists():
        value = json.loads(marker.read_text())
        if value != {"project": PROJECT, "root": str(ROOT)}:
            raise RuntimeError("profile ownership marker mismatch")
        return
    names, _ = command(
        "preexisting-containers", [*DOCKER, "ps", "-a", "--format", "{{.Names}}"], env
    )
    volumes, _ = command(
        "preexisting-volumes", [*DOCKER, "volume", "ls", "--format", "{{.Name}}"], env
    )
    if any(x.startswith(PROJECT + "-") for x in names.splitlines()) or any(
        x.startswith(PROJECT + "_") for x in volumes.splitlines()
    ):
        raise RuntimeError("profile resource collision without ownership marker")
    marker.write_text(json.dumps({"project": PROJECT, "root": str(ROOT)}, indent=2) + "\n")


def backup_live_store(env):
    """Online SQLite backup, including committed WAL state, before migration."""
    ensure_owner(env)
    container, _ = command("backup-service-id", compose_args("ps", "-q", "service"), env)
    if not container or "\n" in container:
        raise RuntimeError("one running service container required for online backup")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    name = "dev07-pre-migration-" + stamp + ".sqlite"
    inside = "/data/" + name
    backups = STATE / "backups"
    backups.mkdir(mode=0o700, exist_ok=True)
    backups.chmod(0o700)
    outside = backups / name
    if outside.exists():
        raise RuntimeError("backup destination collision")
    script = (
        "import os,sqlite3; "
        "source=sqlite3.connect('/data/store.sqlite'); "
        f"target=sqlite3.connect({inside!r}); "
        "source.backup(target); target.close(); source.close(); "
        f"os.chmod({inside!r},0o600)"
    )
    command("backup-sqlite-" + stamp, [*DOCKER, "exec", container, "python", "-c", script], env)
    command("backup-copy-" + stamp, [*DOCKER, "cp", container + ":" + inside, str(outside)], env)
    outside.chmod(0o600)
    # The copied file is a consistent snapshot; inspect it without mutating it.
    with sqlite3.connect("file:" + str(outside) + "?mode=ro", uri=True) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("copied SQLite backup failed quick_check")
        submissions = db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
    command(
        "backup-remove-volume-copy-" + stamp,
        [
            *DOCKER,
            "exec",
            container,
            "python",
            "-c",
            f"from pathlib import Path; Path({inside!r}).unlink()",
        ],
        env,
    )
    summary = {
        "kind": "DEV-07 consistent pre-migration SQLite backup",
        "path": str(outside),
        "sha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
        "bytes": outside.stat().st_size,
        "submissions": submissions,
        "source": "running owned DEV-06 service; SQLite online backup",
        "at": stamp,
    }
    (backups / (name + ".json")).write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, sort_keys=True))


def build_images(build, env):
    source = Path(build["build_dir"])
    for kind in ("receiver", "worker", "service"):
        image = env["EZLLMROUTER_" + kind.upper() + "_IMAGE"]
        _, present = command(
            "inspect-" + kind, [*DOCKER, "image", "inspect", image], env, allowed=(0, 1)
        )
        if present == 0:
            continue
        command(
            "build-" + kind,
            [
                *DOCKER,
                "build",
                "--pull=false",
                "--network=none",
                "--build-arg",
                "PYTHON_IMAGE=" + BASE,
                "-t",
                image,
                "-f",
                str(source / kind / "Dockerfile"),
                str(source / kind),
            ],
            env,
        )


def build_dev07_actors(build, env):
    source = Path(build["build_dir"])
    for kind, image_key, base, argument in (
        ("python", "EZLLMROUTER_DEV07_PYACTOR_IMAGE", BASE, "PYTHON_IMAGE"),
        ("js", "EZLLMROUTER_DEV07_JSACTOR_IMAGE", NODE, "NODE_IMAGE"),
    ):
        image = env[image_key]
        _, present = command(
            "inspect-dev07-" + kind, [*DOCKER, "image", "inspect", image], env, allowed=(0, 1)
        )
        if present == 0:
            continue
        command(
            "build-dev07-" + kind,
            [
                *DOCKER,
                "build",
                "--pull=false",
                "--network=none",
                "--build-arg",
                argument + "=" + base,
                "-t",
                image,
                "-f",
                str(source / kind / "Dockerfile"),
                str(source / kind),
            ],
            env,
        )


def receiver_count(env):
    value, _ = command(
        "receiver-count",
        compose_args(
            "exec",
            "-T",
            "receiver",
            "python",
            "-c",
            "import pathlib; p=pathlib.Path('/data/arrivals.jsonl'); print(len(p.read_text().splitlines()) if p.exists() else 0)",
        ),
        env,
    )
    return int(value)


def check_console_port(env):
    port, _ = command("console-port", compose_args("port", "ingress", "8780"), env)
    if port != "127.0.0.1:8780":
        raise RuntimeError("console loopback port binding missing or unexpected: " + port[:100])


def topology(env):
    command(
        "worker-identity",
        compose_args(
            "exec",
            "-T",
            "service",
            "python",
            "-B",
            "/app/gateway/worker_ready.py",
            "--deadline",
            "5",
            "--allow-activity",
        ),
        env,
    )
    command(
        "ingress-isolation",
        compose_args(
            "exec",
            "-T",
            "ingress",
            "python",
            "-c",
            "import os,pathlib,socket,json\n"
            "assert os.getuid()==10001\n"
            "assert pathlib.Path('/console/operator.sock').is_socket()\n"
            "assert not any(pathlib.Path(x).exists() for x in "
            "('/link','/data','/app/server','/run/ezllmrouter/credentials.json'))\n"
            "try:\n socket.getaddrinfo('netns',8766)\n"
            "except socket.gaierror:\n pass\n"
            "else:\n raise AssertionError('receiver name reachable from ingress')\n"
            "print(json.dumps({'ingress':'console-socket-only','receiver_dns':'unavailable'}))",
        ),
        env,
    )
    before = receiver_count(env)
    command(
        "worker-isolation",
        compose_args(
            "exec",
            "-T",
            "worker",
            "python",
            "-c",
            "import os,pathlib,socket,json; r=pathlib.Path('/proc/net/route').read_text().splitlines(); "
            "assert not any(len(x.split())>1 and x.split()[1]=='00000000' for x in r[1:]); "
            "assert 'EZLLMROUTER_DEV_TOKEN' not in os.environ and 'EZLLMROUTER_DEV04_PROVIDER_KEY' not in os.environ; "
            "assert not any(pathlib.Path(x).exists() for x in ('/app/server','/app/dev_slice','/app/gateway')); "
            "s=socket.socket(); s.settimeout(.5); rc=s.connect_ex(('127.0.0.1',8766)); s.close(); "
            "assert rc!=0; print(json.dumps({'worker_network':'none','direct_receiver_errno':rc}))",
        ),
        env,
    )
    command(
        "forged-attempt",
        compose_args(
            "exec",
            "-T",
            "worker",
            "python",
            "-c",
            "import socket,json,base64; from choice_b_wire import send,receive; "
            "s=socket.socket(socket.AF_UNIX); s.connect('/link/sender.sock'); "
            "send(s,{'kind':'final_request','attempt_id':'attempt.'+'0'*32,'method':'POST',"
            "'url':'http://127.0.0.1:8766/v1/chat/completions','headers':[],"
            "'body_b64':base64.b64encode(b'{}').decode(),'timeout':{}}); "
            "r=receive(s); s.close(); assert r=={'error_type':'ValueError'},r; print(json.dumps(r))",
        ),
        env,
    )
    if receiver_count(env) != before:
        raise RuntimeError("topology negative added receiver arrival")
    return before


def audit_live(build, env):
    """Correlate one recorded synthetic exercise with independent receiver metadata."""
    receipt = json.loads((STATE / "last-explicit-exercise.json").read_text())
    ids = receipt.get("submission_ids")
    if (
        receipt.get("kind") != "DEV-06 explicit synthetic operator exercise"
        or type(ids) is not list
        or len(ids) != 4
        or any(type(value) is not str for value in ids)
        or len(set(ids)) != 4
        or receipt.get("no_store_submission_id") != ids[-1]
        or receipt.get("caller_lookups") != 1
        or receipt.get("provider_requests_expected_delta") != 4
        or type(receipt.get("before_submissions")) is not int
        or type(receipt.get("after_submissions")) is not int
        or receipt["after_submissions"] - receipt["before_submissions"] != 4
    ):
        raise RuntimeError("explicit exercise receipt malformed")
    _, password = secrets_on_disk()
    client, overview = wait_health(password, seconds=10)
    if overview["build"]["fingerprint"] != build["fingerprint"]:
        raise RuntimeError("running build differs from staged profile")
    independent_count = topology(env)
    details = [client.call("GET", "/operator/v1/activity/" + sid) for sid in ids]
    for sid, item in zip(ids, details):
        if (
            item["submission_id"] != sid
            or item["submission_state"] != "completed"
            or item["dispatch_state"] != "response_observed"
            or item["intent"]["present"] is not True
            or item["dispatch_receipt"]["present"] is not True
        ):
            raise RuntimeError("exercise submission lacks completed intent/receipt")
    if (
        details[-1]["candidate_access"] != "not_retained"
        or details[-1]["content_store_allowed"] is not False
    ):
        raise RuntimeError("no-store exercise metadata mismatch")
    if any(item["candidate_access"] != "present" for item in details[:-1]):
        raise RuntimeError("retained exercise metadata mismatch")
    code = (
        "import json,pathlib; p=pathlib.Path('/data/arrivals.jsonl'); "
        "rows=[json.loads(s) for s in p.read_text().splitlines()] if p.exists() else []; "
        "print(json.dumps([{k:r[k] for k in ('attempt_id','body_sha256','body_bytes')} "
        "for r in rows]))"
    )
    output, _ = command(
        "audit-receiver", compose_args("exec", "-T", "receiver", "python", "-c", code), env
    )
    arrivals = json.loads(output)
    if type(arrivals) is not list or len(arrivals) != independent_count:
        raise RuntimeError("independent receiver count changed during audit")
    by_attempt = {}
    for row in arrivals:
        if type(row) is not dict or set(row) != {"attempt_id", "body_sha256", "body_bytes"}:
            raise RuntimeError("independent receiver row malformed")
        by_attempt.setdefault(row["attempt_id"], []).append(row)
    if any(len(rows) != 1 for rows in by_attempt.values()):
        raise RuntimeError("receiver recorded a duplicate attempt")
    for item in details:
        rows = by_attempt.get(item["attempt_id"], [])
        dispatch = item["dispatch_receipt"]
        if (
            len(rows) != 1
            or rows[0]["body_sha256"] != dispatch["body_sha256"]
            or rows[0]["body_bytes"] != dispatch["body_bytes"]
        ):
            raise RuntimeError("receiver arrival and guard receipt mismatch")
    result = {
        "kind": "DEV-06 read-only live correlation",
        "build": overview["build"],
        "service": overview["service"]["state"],
        "worker": overview["worker"]["state"],
        "sender": overview["sender"]["state"],
        "preexisting_submissions": receipt["before_submissions"],
        "exercise_submission_delta": 4,
        "receiver_arrivals_total": independent_count,
        "matched_exercise_attempts": 4,
        "single_arrival_per_receiver_attempt": True,
        "no_store_candidate_access": details[-1]["candidate_access"],
        "caller_lookups_in_exercise": 1,
        "topology_negative_added_arrivals": False,
    }
    (STATE / "last-live-audit.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True))


def verify_persistence(build, env):
    """Read back completed work across an owned, ordinary no-build stop/start."""
    receipt = json.loads((STATE / "last-explicit-exercise.json").read_text())
    audit = json.loads((STATE / "last-live-audit.json").read_text())
    if (
        audit.get("kind") != "DEV-06 read-only live correlation"
        or audit.get("build", {}).get("fingerprint") != build["fingerprint"]
        or audit.get("matched_exercise_attempts") != 4
        or audit.get("single_arrival_per_receiver_attempt") is not True
        or audit.get("topology_negative_added_arrivals") is not False
        or type(receipt.get("submission_ids")) is not list
        or len(receipt["submission_ids"]) != 4
        or receipt.get("no_store_submission_id") != receipt["submission_ids"][-1]
    ):
        raise RuntimeError("recorded live audit/exercise unavailable for persistence check")
    _, password = secrets_on_disk()
    _, before = wait_health(password, seconds=10)
    counts = before["counts"]
    if (
        before["build"]["fingerprint"] != build["fingerprint"]
        or type(counts["submissions"]) is not int
        or counts["submissions"] < receipt["after_submissions"]
        or counts["completed"] != counts["submissions"]
        or counts["known_failures"] != 0
        or counts["unknown_outcomes"] != 0
    ):
        raise RuntimeError("profile is not quiescent at recorded build")
    readback(password, receipt)
    arrivals_before = receiver_count(env)
    if arrivals_before != audit["receiver_arrivals_total"]:
        raise RuntimeError("receiver inventory changed since live audit")
    command("persistence-stop", compose_args("down", "--remove-orphans"), env)
    # Use the existing images, staged ingress and named volumes. A failure leaves
    # the owned profile available for diagnosis; no automatic resend or cleanup.
    command("persistence-up", compose_args("up", "-d", "--no-build"), env)
    check_console_port(env)
    _, after = wait_health(password)
    if after["build"]["fingerprint"] != build["fingerprint"] or after["counts"] != counts:
        raise RuntimeError("normal restart changed build or submission accounting")
    result = readback(password, receipt)
    if receiver_count(env) != arrivals_before:
        raise RuntimeError("normal restart added receiver arrival")
    if topology(env) != arrivals_before:
        raise RuntimeError("post-restart topology changed receiver inventory")
    output = {
        "kind": "DEV-06 ordinary stop/start metadata readback",
        "build": after["build"],
        "submissions": counts["submissions"],
        "receiver_arrivals_before": arrivals_before,
        "receiver_arrivals_after": arrivals_before,
        "new_provider_requests": 0,
        "readback": result,
    }
    (STATE / "last-persistence-check.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, sort_keys=True))


def capture_failed_start(env):
    """Keep bounded, redacted container evidence before failure-down removes it."""
    for name, args in (
        ("failure-ps", compose_args("ps", "--all")),
        (
            "failure-logs",
            compose_args(
                "logs",
                "--no-color",
                "--tail=80",
                "service",
                "worker",
                "receiver",
                "netns",
                "ingress",
            ),
        ),
        ("failure-console-port", compose_args("port", "ingress", "8780")),
        (
            "failure-console-socket",
            compose_args(
                "exec",
                "-T",
                "service",
                "python",
                "-c",
                "import socket; s=socket.socket(socket.AF_UNIX); s.settimeout(2); "
                "print('console_socket_connect_errno=' + str(s.connect_ex('/console/operator.sock'))); s.close()",
            ),
        ),
    ):
        try:
            command(name, args, env, allowed=(0, 1))
        except Exception:
            pass
    path = STATE / "commands/failure-logs.stdout"
    if path.exists():
        lines = path.read_text().splitlines()[-25:]
        if lines:
            print("Redacted startup log tail:", file=sys.stderr)
            print("\n".join(lines)[-3000:], file=sys.stderr)
    for name in ("failure-console-port", "failure-console-socket"):
        output = STATE / "commands" / (name + ".stdout")
        if output.exists():
            print(name + ": " + (output.read_text().strip()[:200] or "no output"), file=sys.stderr)


def profile_up(verify_demos=False):
    credentials, password = secrets_on_disk()
    command(
        "prepare", [sys.executable, "-I", "-B", str(LOCAL / "prepare.py")], env=os.environ.copy()
    )
    build = current()
    env = environment(build)
    ensure_owner(env)
    command("compose-config", compose_args("config", "--quiet"), env)
    prior, _ = command("preexisting-profile", compose_args("ps", "-q"), env)
    if prior.strip():
        raise RuntimeError("profile already has containers; use status or stop before another up")
    build_images(build, env)
    # Stdin keeps secret bytes out of argv, Docker configuration and command logs.
    command(
        "initialize-credentials",
        compose_args("run", "--rm", "-T", "--no-deps", "credential-init"),
        env,
        input_data=json.dumps({"credentials": credentials, "operator_password": password}),
    )
    created_new = True
    started = False
    try:
        started = True
        command("up", compose_args("up", "-d", "--no-build"), env)
        check_console_port(env)
        print(
            "Local profile: waiting up to 60 seconds for operator and worker readiness…", flush=True
        )
        client, overview = wait_health(password)
        initial = topology(env)
        if verify_demos:
            receipt = exercise(password)
            after = receiver_count(env)
            if after - initial != 4:
                raise RuntimeError("synthetic receiver inventory mismatch")
            receipt.update(
                receiver_before=initial,
                receiver_after=after,
                build_fingerprint=build["fingerprint"],
            )
            (STATE / "last-explicit-verification.json").write_text(
                json.dumps(receipt, indent=2) + "\n"
            )
            command("quiescent-stop", compose_args("down", "--remove-orphans"), env)
            command("restart", compose_args("up", "-d", "--no-build"), env)
            check_console_port(env)
            result = readback(password, receipt)
            if receiver_count(env) != after:
                raise RuntimeError("normal restart added receiver arrival")
            topology(env)
            print(
                json.dumps(
                    {
                        "verification": "PASS",
                        "receiver_delta": 4,
                        "caller_lookups": 1,
                        "readback": result,
                    },
                    sort_keys=True,
                )
            )
        else:
            print(
                json.dumps(
                    {
                        "readiness": "PASS",
                        "service": overview["service"]["state"],
                        "worker": overview["worker"]["state"],
                    },
                    sort_keys=True,
                )
            )
        print("Running console: http://127.0.0.1:8780/")
        print("Operator credential file: " + str(STATE / "operator-password"))
        print("Stop, preserving metadata volumes: python3 " + str(LOCAL / "profile.py") + " stop")
    except Exception:
        if started and created_new:
            capture_failed_start(env)
            try:
                command("failure-down", compose_args("down", "--remove-orphans"), env)
            except Exception:
                pass
        raise


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in (
        "prepare",
        "up",
        "up-and-verify",
        "restart",
        "audit",
        "verify-persistence",
        "status",
        "stop",
        "diagnose",
        "backup",
        "build-images",
        "build-actors",
    ):
        raise SystemExit(
            "usage: profile.py prepare|up|up-and-verify|restart|audit|verify-persistence|status|stop|diagnose|backup|build-images|build-actors"
        )
    action = sys.argv[1]
    if action == "prepare":
        command(
            "prepare",
            [sys.executable, "-I", "-B", str(LOCAL / "prepare.py")],
            env=os.environ.copy(),
        )
        print(json.dumps({"prepared": current()["fingerprint"], "docker_executed": False}))
        return
    if action in ("up", "up-and-verify"):
        profile_up(verify_demos=action == "up-and-verify")
        return
    build = current()
    env = environment(build)
    if not (STATE / "PROFILE-OWNER.json").exists():
        raise SystemExit("local profile ownership marker missing")
    if action == "backup":
        backup_live_store(env)
        return
    if action == "build-images":
        ensure_owner(env)
        build_images(build, env)
        return
    if action == "build-actors":
        ensure_owner(env)
        build_dev07_actors(build, env)
        return
    if action == "audit":
        ensure_owner(env)
        audit_live(build, env)
        return
    if action == "verify-persistence":
        ensure_owner(env)
        verify_persistence(build, env)
        return
    if action == "restart":
        ensure_owner(env)
        command("restart-stop", compose_args("down", "--remove-orphans"), env)
        profile_up()
        return
    if action == "diagnose":
        status, _ = command("diagnose-ps", compose_args("ps", "--all"), env, allowed=(0, 1))
        logs, _ = command(
            "diagnose-logs",
            compose_args(
                "logs", "--no-color", "--tail=80", "service", "worker", "receiver", "netns"
            ),
            env,
            allowed=(0, 1),
        )
        log_error = (
            (STATE / "commands/diagnose-logs.stderr").read_text()
            if (STATE / "commands/diagnose-logs.stderr").exists()
            else ""
        )
        print("Redacted container status:\n" + (status[-2500:] or "No profile containers listed."))
        print(
            "Redacted startup log tail:\n"
            + (
                "\n".join((logs or log_error).splitlines()[-40:])[-5000:]
                or "No profile container logs available."
            )
        )
        return
    if action == "stop":
        command("stop", compose_args("down", "--remove-orphans"), env)
        print("Stopped. Metadata, receiver and link volumes preserved.")
    else:
        output, _ = command("status", compose_args("ps"), env)
        print(output)
        _, password = secrets_on_disk()
        _, overview = wait_health(password, seconds=2)
        print(
            json.dumps(
                {
                    "service": overview["service"]["state"],
                    "worker": overview["worker"]["state"],
                    "sender": overview["sender"]["state"],
                },
                sort_keys=True,
            )
        )


def run_cli():
    try:
        main()
    except Exception as exc:
        STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
        safe = {
            "stage": "local profile",
            "error_type": type(exc).__name__,
            "message": redact(str(exc))[:500],
            "docker_target_completed": False,
        }
        (STATE / "last-error.json").write_text(json.dumps(safe, indent=2) + "\n")
        print(
            "local profile failed: " + safe["error_type"] + ": " + safe["message"], file=sys.stderr
        )
        raise SystemExit(1)


if __name__ == "__main__":
    run_cli()
