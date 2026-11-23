"""Qualify a clean staged build in fresh, explicitly owned Docker projects."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import shutil
import socket
import tempfile
import zipfile
from pathlib import Path

from deploy.local import local_profile as profile
from tools.qualification_storage import cold_copy, owned_volume
from tools.gateway.os_inputs import verify_staging as verify_os_staging


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def validate_staging(build: dict) -> str:
    verify_os_staging(build)
    root = Path(build["build_dir"])
    overlays = {row["path"]: row for row in build["overlays"]}
    with zipfile.ZipFile(build["source_packet"]) as packet:
        sources = json.loads(packet.read("SOURCE-MANIFEST.json"))["source_files"]
        for row in sources:
            if row["target"] not in overlays:
                path = root / row["target"]
                if (
                    path.is_symlink()
                    or not path.is_file()
                    or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]
                ):
                    raise ValueError("staged source identity mismatch")
    for row in overlays.values():
        path = root / row["path"]
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size != row["bytes"]
            or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]
        ):
            raise ValueError("staged overlay identity mismatch")
    return hashlib.sha256(Path(build["source_packet"]).read_bytes()).hexdigest()


def select(state: Path, project: str) -> None:
    if (
        not project.startswith("ezllmrouter-qualification-")
        or state.resolve() == (profile.LOCAL / ".state").resolve()
    ):
        raise ValueError("disposable qualification state and project required")
    profile.STATE, profile.PROJECT = state, project
    state.mkdir(mode=0o700)


def build_images(build: dict, env: dict[str, str], project: str) -> dict:
    result = {}
    bases = verify_os_staging(build)["bases"]
    os_lock = build["os_inputs"]["lock"]
    for kind in ("runtime_python", "receiver", "worker", "service", "python", "js"):
        image = project + ":" + kind
        key = {
            "python": "EZLLMROUTER_DEV07_PYACTOR_IMAGE",
            "js": "EZLLMROUTER_DEV07_JSACTOR_IMAGE",
            "runtime_python": "EZLLMROUTER_PYTHON_IMAGE",
        }.get(kind, "EZLLMROUTER_" + kind.upper() + "_IMAGE")
        env[key] = image
        argument, base = (
            ("NODE_IMAGE", bases["node"]["reference"])
            if kind == "js"
            else ("PYTHON_IMAGE", bases["python"]["reference"])
        )
        profile.command(
            "build-" + kind,
            [
                *profile.DOCKER,
                "build",
                "--pull=false",
                "--network=none",
                "--progress=plain",
                "--build-arg",
                argument + "=" + base,
                "--label",
                "com.ezllmrouter.qualification.project=" + project,
                "--label",
                "org.opencontainers.image.revision=" + build["commit"],
                "--label",
                "com.ezllmrouter.qualification.source=" + build["fingerprint"],
                "-t",
                image,
                str(Path(build["build_dir"]) / kind),
            ],
            env,
        )
        raw, _ = profile.command("image-" + kind, [*profile.DOCKER, "image", "inspect", image], env)
        row = json.loads(raw)[0]
        if row["Config"]["Labels"]["com.ezllmrouter.qualification.source"] != build["fingerprint"]:
            raise ValueError("built image source mismatch")
        result[kind] = {
            "tag": image,
            "id": row["Id"],
            "architecture": row["Architecture"],
            "base": base,
        }
        raw, _ = profile.command(
            "runtime-os-" + kind,
            [
                *profile.DOCKER,
                "run",
                "--rm",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges:true",
                row["Id"],
                "dpkg-query",
                "-W",
                "-f=${binary:Package}\t${Version}\t${db:Status-Status}\n",
            ],
            env,
        )
        installed = {}
        for line in raw.splitlines():
            name, version, status = line.split("\t")
            if status == "installed":
                installed[name.split(":", 1)[0]] = version
        role = "node" if kind == "js" else "python"
        selected = [item for item in os_lock["packages"] if role in item["roles"]]
        if any(installed.get(item["package"]) != item["version"] for item in selected):
            raise ValueError("runtime OS differs from reviewed package inputs")
        if {"apt", "libapt-pkg7.0", "sqv"} & set(installed):
            raise ValueError("APT tooling remains in runtime")
        result[kind]["os_lock_sha256"] = build["os_inputs"]["lock_sha256"]
        probe = (
            [
                "node",
                "-e",
                "const fs=require('node:fs');for(const p of ['/usr/local/lib/node_modules','/usr/local/bin/npm','/usr/local/bin/corepack','/usr/local/bin/yarn'])if(fs.existsSync(p))throw Error('package installer in runtime');",
            ]
            if kind == "js"
            else [
                "python",
                "-I",
                "-c",
                "import importlib.util; assert all(importlib.util.find_spec(n) is None for n in ('pip','ensurepip'))",
            ]
        )
        profile.command(
            "runtime-installers-" + kind,
            [
                *profile.DOCKER,
                "run",
                "--rm",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges:true",
                row["Id"],
                *probe,
            ],
            env,
        )
    return result


def structure(env: dict[str, str]) -> dict:
    ids, _ = profile.command("container-ids", profile.compose_args("ps", "-q"), env)
    if not ids.splitlines():
        raise ValueError("no qualification containers")
    raw, _ = profile.command(
        "container-inspect", [*profile.DOCKER, "inspect", *ids.splitlines()], env
    )
    rows = json.loads(raw)
    project = profile.profile_project()
    result = {}
    for row in rows:
        labels, host = row["Config"]["Labels"], row["HostConfig"]
        kind = labels["com.docker.compose.service"]
        if (
            labels["com.docker.compose.project"] != project
            or row["Config"]["User"] != "10001:10001"
            or not host["ReadonlyRootfs"]
            or "ALL" not in host["CapDrop"]
            or host["CapAdd"]
            or not any(option.startswith("no-new-privileges") for option in host["SecurityOpt"])
        ):
            raise ValueError("runtime isolation configuration mismatch: " + kind)
        mounts = {mount["Destination"]: mount for mount in row["Mounts"]}
        for mount in mounts.values():
            if mount["Type"] == "volume" and not mount["Name"].startswith(project + "_"):
                raise ValueError("foreign volume in disposable target")
        if kind == "worker" and (
            host["NetworkMode"] != "none"
            or mounts["/link/sender"]["RW"]
            or set(mounts) != {"/link/worker", "/link/sender"}
        ):
            raise ValueError("worker isolation mismatch")
        if kind == "service" and mounts["/run/ezllmrouter"]["RW"]:
            raise ValueError("service credentials mount is writable")
        result[kind] = {
            "readonly_root": True,
            "uid_gid": row["Config"]["User"],
            "network_mode": host["NetworkMode"],
            "mounts": sorted(mounts),
        }
    if set(result) != {"netns", "receiver", "worker", "service", "ingress"}:
        raise ValueError("unexpected qualification service inventory")
    profile.command(
        "credential-modes",
        profile.compose_args(
            "exec",
            "-T",
            "service",
            "python",
            "-c",
            "import os,stat; from pathlib import Path; p=Path('/run/ezllmrouter'); "
            "assert stat.S_IMODE(p.stat().st_mode)==0o711; "
            "files=list(p.iterdir()) if os.getuid()==0 else [p/'credentials.json',p/'operator-password']; "
            "assert all(f.stat().st_uid==10001 and stat.S_IMODE(f.stat().st_mode)==0o400 for f in files)",
        ),
        env,
    )
    return result


def vault_probe(env: dict[str, str], *, create: bool) -> None:
    code = (
        "import json,sys; from ezllmrouter_server.provider_vault import ProviderVault; "
        "v=ProviderVault('/data/provider-vault'); value=json.load(sys.stdin)['canary']; "
        + ("v.seal('connection.qualification',1,value); " if create else "")
        + "assert v.resolve('connection.qualification',1)==value; print('vault canary verified')"
    )
    profile.command(
        "vault-seed" if create else "vault-readback",
        profile.compose_args("exec", "-T", "service", "python", "-c", code),
        env,
        input_data=json.dumps({"canary": "qualification-only-canary-no-provider-authority"}),
    )


def installed_readers(env: dict[str, str], token: str, receipt: dict) -> dict:
    netns, _ = profile.command("client-netns", profile.compose_args("ps", "-q", "netns"), env)
    if not re.fullmatch(r"[0-9a-f]{64}", netns):
        raise ValueError("one owned client network namespace required")
    scripts = {
        "python": (
            "python",
            "-c",
            "import json,sys; from ezllmrouter_client import EzLLMRouterClient; v=json.load(sys.stdin); "
            "c=EzLLMRouterClient('http://127.0.0.1:8773',v['token']); s=c.getStatus({'submission_id':v['sid']}); c.close(); "
            "assert s['handle']['submission_id']==v['sid'] and s['submission_state']=='completed'; print('installed Python readback passed')",
        ),
        "js": (
            "node",
            "-e",
            "const fs=require('node:fs');const {EzLLMRouterClient}=require('@cognitivedynamics/ezllmrouter-client');"
            "const v=JSON.parse(fs.readFileSync(0,'utf8'));const c=new EzLLMRouterClient({baseUrl:'http://127.0.0.1:8773',token:v.token});"
            "c.getStatus({submission_id:v.sid}).then(s=>{if(s.handle.submission_id!==v.sid||s.submission_state!=='completed')throw Error('readback');"
            "console.log('installed JavaScript readback passed');}).catch(()=>{process.exitCode=1;});",
        ),
    }
    before = profile.receiver_count(env)
    for kind, script in scripts.items():
        key = "EZLLMROUTER_DEV07_" + ("PYACTOR" if kind == "python" else "JSACTOR") + "_IMAGE"
        profile.command(
            "installed-" + kind,
            [
                *profile.DOCKER,
                "run",
                "--rm",
                "-i",
                "--network=container:" + netns,
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges:true",
                env[key],
                *script,
            ],
            env,
            input_data=json.dumps({"token": token, "sid": receipt["submission_ids"][0]}),
        )
    if profile.receiver_count(env) != before:
        raise ValueError("client metadata readback sent a provider request")
    return {"python": "passed", "javascript": "passed", "new_provider_requests": 0}


def missing_key_probe(project: str, env: dict[str, str]) -> None:
    volume = owned_volume(project, "service_data", env)
    code = """
from pathlib import Path
from ezllmrouter_server.provider_vault import ProviderVault
from ezllmrouter_server.secret_box import SecretBoxError
p=Path('/data/provider-vault/provider.keys.json')
saved=p.with_suffix('.qualification-held')
p.rename(saved)
try:
    try:
        ProviderVault(p.parent)
    except SecretBoxError:
        assert not p.exists()
    else:
        raise AssertionError('incomplete restore accepted')
finally:
    saved.rename(p)
print('missing-key restore fails closed')
"""
    profile.command(
        "missing-key-restore",
        [
            *profile.DOCKER,
            "run",
            "--rm",
            "--network=none",
            "--read-only",
            "--user=10001:10001",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--mount",
            "type=volume,src=" + volume + ",dst=/data",
            env["EZLLMROUTER_SERVICE_IMAGE"],
            "python",
            "-c",
            code,
        ],
        env,
    )


def run(build: dict, output: Path) -> dict:
    if build.get("dirty") is not False or not re.fullmatch(
        r"[0-9a-f]{40}", build.get("commit", "")
    ):
        raise ValueError("clean committed staging required")
    packet_sha = validate_staging(build)
    # Refuse a busy console port before any Docker mutation.
    with socket.socket() as check:
        check.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        check.bind(("127.0.0.1", 8780))
    output.mkdir(parents=True, exist_ok=False)
    project = "ezllmrouter-qualification-" + secrets.token_hex(6)
    result = {
        "kind": "disposable deployment qualification",
        "source_commit": build["commit"],
        "source_fingerprint": build["fingerprint"],
        "source_packet_sha256": packet_sha,
        "project": project,
        "status": "incomplete",
        "harness_sha256": {
            name: hashlib.sha256((profile.ROOT / name).read_bytes()).hexdigest()
            for name in (
                "tools/deployment_qualification.py",
                "tools/qualification_storage.py",
                "tools/volume_archive.py",
                "deploy/local/local_profile.py",
                "deploy/local/check.py",
                "tools/gateway/os_inputs.py",
                "deploy/local/install_os.sh",
                "deploy/local/inputs/os/debian13-arm64.lock.json",
            )
        },
    }
    owned = []
    with tempfile.TemporaryDirectory(prefix="ezllmrouter-qualification-") as temporary:
        root = Path(temporary)
        env = profile.environment(build)
        try:
            select(root / "original", project)
            credentials, password = profile.secrets_on_disk()
            profile.ensure_owner(env)
            owned.append((profile.STATE, project))
            result["images"] = build_images(build, env, project)
            profile.command("compose-config", profile.compose_args("config", "--quiet"), env)
            profile.command(
                "credentials-init",
                profile.compose_args("run", "--rm", "-T", "--no-deps", "credential-init"),
                env,
                input_data=json.dumps({"credentials": credentials, "operator_password": password}),
            )
            profile.command("up", profile.compose_args("up", "-d", "--no-build"), env)
            profile.check_console_port(env)
            _, overview = profile.wait_health(password)
            if (
                overview["build"]["fingerprint"] != build["fingerprint"]
                or profile.topology(env) != 0
            ):
                raise ValueError("fresh target identity or initial receiver mismatch")
            result["structure"] = structure(env)
            receipt = profile.exercise(password)
            result["installed_client_readers"] = installed_readers(
                env, credentials["service_token"], receipt
            )
            write(profile.STATE / "last-explicit-exercise.json", receipt)
            profile.audit_live(build, env)
            profile.verify_persistence(build, env)
            vault_probe(env, create=True)
            result["exercise"] = receipt
            result["restart"] = json.loads(
                (profile.STATE / "last-persistence-check.json").read_text()
            )
            profile.command(
                "cold-backup-stop", profile.compose_args("down", "--remove-orphans"), env
            )
            original_state = profile.STATE
            restore = project + "-restore"
            select(root / "restored", restore)
            profile.ensure_owner(env)
            owned.append((profile.STATE, restore))
            # Keep redaction of the restored target bound to the same generated secrets.
            shutil.copy2(
                original_state / "profile-secrets.json", profile.STATE / "profile-secrets.json"
            )
            # Create empty Compose-labelled volumes, without starting services.
            profile.command("restore-create", profile.compose_args("create", "--no-build"), env)
            result["backup"] = cold_copy(project, restore, root, env)
            missing_key_probe(restore, env)
            profile.command("restore-up", profile.compose_args("up", "-d", "--no-build"), env)
            _, restored = profile.wait_health(password)
            if (
                restored["counts"]["submissions"] != 4
                or restored["build"]["fingerprint"] != build["fingerprint"]
            ):
                raise ValueError("restored accounting or source identity mismatch")
            result["restore_readback"] = profile.readback(password, receipt)
            if profile.topology(env) != 4:
                raise ValueError("restore replayed or lost a receiver arrival")
            vault_probe(env, create=False)
            result["restore_structure"] = structure(env)
            shutil.copy2(original_state / "last-live-audit.json", output / "live-audit.json")
            result["status"] = "passed"
        except Exception as exc:
            result["failure_type"] = type(exc).__name__
            profile.command(
                "failure-logs",
                profile.compose_args(
                    "logs", "--no-color", "--tail", "100", "service", "worker", "receiver"
                ),
                env,
                allowed=(0, 1),
            )
            raise
        finally:
            # Only projects whose fresh local ownership marker was created above.
            for state, name in reversed(owned):
                profile.STATE, profile.PROJECT = state, name
                if profile.profile_project() != name or not name.startswith(
                    "ezllmrouter-qualification-"
                ):
                    raise ValueError("cleanup ownership mismatch")
                profile.command(
                    "qualification-cleanup",
                    profile.compose_args("down", "--volumes", "--remove-orphans"),
                    env,
                )
                shutil.copytree(state / "commands", output / name)
            result["cleanup_complete"] = True
            write(output / "qualification.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build = json.loads(args.build.read_text())
    result = run(build, args.output)
    print(json.dumps({"status": result["status"], "source_commit": result["source_commit"]}))


if __name__ == "__main__":
    main()
