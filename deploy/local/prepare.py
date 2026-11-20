#!/usr/bin/env python3
"""Stage the persistent profile from tracked source and declared frozen artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib


ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "deploy/local/.state"
PYTHON_CLIENT = tomllib.loads((ROOT / "clients/python/pyproject.toml").read_text(encoding="utf-8"))[
    "project"
]
JS_CLIENT = json.loads((ROOT / "clients/js/package.json").read_text(encoding="utf-8"))
DEV09_CLIENT = (
    re.sub(r"[-_.]+", "_", PYTHON_CLIENT["name"])
    + "-"
    + PYTHON_CLIENT["version"]
    + "-py3-none-any.whl"
)
JS_ARCHIVE = JS_CLIENT["name"].lstrip("@").replace("/", "-") + "-" + JS_CLIENT["version"] + ".tgz"
SOURCE_ROOTS = (
    "server",
    "tests/gateway_integration",
    "tests/development_slice",
    "tests/tool_cycle",
    "tests/operator_console",
    "clients/python",
    "clients/js",
    "deploy/local",
    "tools/gateway",
    "tools/operator",
    "worker",
    "web",
)
FIXED_INPUTS = (
    "deploy/local/inputs/gateway/WHEEL-INVENTORY.json",
    "deploy/local/inputs/gateway/requirements.gateway.lock",
    "tests/fixtures/contracts/wp-a-03-c01/EZLLMROUTER-WP-A-VECTORS-v0.3-CORRECTION-01.json",
)


def package_artifacts(directory):
    # uv creates a local .gitignore in a new output directory. It is not a
    # package input, and the actual wheel/tarball inventory stays exact.
    return {item.name for item in directory.iterdir() if item.name != ".gitignore"}


def git(*args):
    return subprocess.check_output(("git", *args), cwd=ROOT).decode().strip()


def source_dirty():
    # Unrelated untracked documents do not enter the staged image. Still block
    # every edited tracked source/input and any new file under a staged root.
    return bool(
        git("status", "--porcelain", "--untracked-files=normal", "--", *SOURCE_ROOTS, *FIXED_INPUTS)
    )


def reuse_client_wheel(sdk_out):
    """Reuse a clean local wheel only when its committed SDK source is identical."""
    if source_dirty():
        return None
    current_tree = git("rev-parse", "HEAD:clients/python")
    for path in sorted(
        (STATE / "staging").glob("source-*/LOCAL-BUILD-MANIFEST.json"), reverse=True
    ):
        try:
            prior = json.loads(path.read_text())
            commit = prior.get("commit", "")
            if prior.get("dirty") is not False or not re.fullmatch(r"[0-9a-f]{40}", commit):
                continue
            if git("rev-parse", f"{commit}:clients/python") != current_tree:
                continue
            wheel = path.parent / "sdk" / DEV09_CLIENT
            if not wheel.is_file() or hashlib.sha256(wheel.read_bytes()).hexdigest() != prior.get(
                "dev09_client_wheel_sha256"
            ):
                continue
            shutil.copy2(wheel, sdk_out / DEV09_CLIENT)
            return {
                "source_commit": commit,
                "source_wheel_sha256": prior["dev09_client_wheel_sha256"],
            }
        except (OSError, ValueError, subprocess.CalledProcessError):
            continue
    return None


def fingerprint():
    listed = subprocess.check_output(
        (
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            *SOURCE_ROOTS,
        ),
        cwd=ROOT,
    )
    paths = [Path(raw.decode()) for raw in listed.split(b"\0") if raw]
    paths = [
        rel
        for rel in paths
        if (ROOT / rel).is_file()
        and not rel.name.endswith((".pyc", ".zip", ".whl", ".tgz", ".tar.gz", ".md"))
    ]
    paths.extend(Path(item) for item in FIXED_INPUTS)
    paths.sort(key=str)
    digest = hashlib.sha256()
    digest.update(git("rev-parse", "HEAD").encode())
    digest.update(b"dirty" if source_dirty() else b"clean")
    for rel in paths:
        path = ROOT / rel
        if not path.is_file():
            continue
        digest.update(str(rel).encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def main():
    artifact = os.environ.get("EZLLMROUTER_ARTIFACT_ROOT")
    if not artifact:
        raise SystemExit("EZLLMROUTER_ARTIFACT_ROOT is required; see deploy/local/README.md")
    artifact = Path(artifact).resolve()
    if not (artifact / "ARTIFACT-CUSTODY.json").is_file():
        raise SystemExit("declared artifact custody manifest missing")
    custody = json.loads((artifact / "ARTIFACT-CUSTODY.json").read_text())
    if len(custody.get("items", [])) != 177:
        raise SystemExit("unexpected artifact custody inventory")
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(STATE, 0o700)
    source_hash = fingerprint()
    run = STATE / "staging" / ("source-" + source_hash[:16])
    ready = run / "LOCAL-BUILD-MANIFEST.json"
    if ready.exists():
        value = json.loads(ready.read_text())
        if value.get("fingerprint") != source_hash:
            raise SystemExit("staging fingerprint collision")
        (STATE / "current-build.json").write_text(json.dumps(value, indent=2) + "\n")
        print(json.dumps(value, sort_keys=True))
        return
    if run.exists():
        raise SystemExit("partial staging directory requires manual inspection: " + str(run))
    run.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="." + run.name + "-", dir=run.parent))
    try:
        prepare_work(work, run, source_hash, artifact)
    finally:
        if work.exists():
            shutil.rmtree(work)


def copy_web_assets(source, destination):
    destination.mkdir()
    for asset in sorted(source.iterdir()):
        if asset.is_file() and asset.suffix in {
            ".html",
            ".css",
            ".js",
            ".json",
            ".svg",
            ".ico",
            ".png",
            ".woff2",
        }:
            shutil.copy2(asset, destination / asset.name)


def prepare_work(work, run, source_hash, artifact):
    # Keep failed offline builds outside the fingerprinted cache entry. The
    # source packet moves with the completed context in the final rename.
    env = dict(os.environ, EZLLMROUTER_ARTIFACT_ROOT=str(artifact))
    subprocess.run(
        (
            sys.executable,
            "-I",
            "-B",
            str(ROOT / "tools/gateway/stage.py"),
            str(ROOT),
            str(work),
            str(work),
            "DEV-05",
        ),
        check=True,
        env=env,
        stdout=subprocess.DEVNULL,
        timeout=900,
    )
    source_packet = "DEV-05-SOURCE-" + run.name + ".zip"
    (work / ("DEV-05-SOURCE-" + work.name + ".zip")).rename(work / source_packet)
    build = work / "build"
    sdk_out = work / "sdk"
    sdk_out.mkdir()
    reused_client = reuse_client_wheel(sdk_out)
    if reused_client is None:
        subprocess.run(
            (
                "uv",
                "build",
                "--offline",
                "--wheel",
                str(ROOT / "clients/python"),
                "-o",
                str(sdk_out),
            ),
            check=True,
            env=env,
            stdout=subprocess.DEVNULL,
            timeout=900,
        )
    wheel = sdk_out / DEV09_CLIENT
    if not wheel.is_file() or package_artifacts(sdk_out) != {DEV09_CLIENT}:
        raise RuntimeError("offline client wheel does not match clients/python/pyproject.toml")
    shutil.copy2(ROOT / "deploy/local/Dockerfile.service", build / "service/Dockerfile")
    shutil.copy2(ROOT / "deploy/local/Dockerfile.worker", build / "worker/Dockerfile")
    shutil.copy2(ROOT / "deploy/local/local_worker.py", build / "worker/local_worker.py")
    shutil.copy2(ROOT / "deploy/local/socket_lease.py", build / "worker/socket_lease.py")
    shutil.copy2(
        ROOT / "tests/gateway_integration/test_provider_worker_target.py",
        build / "worker/test_provider_worker_target.py",
    )
    shutil.copy2(
        ROOT / "tools/gateway/evidence/dev07_target_preflight.py",
        build / "service/gateway/dev07_target_preflight.py",
    )
    for name in (
        "dev08_integrated.py",
        "dev08_tls_receiver.py",
        "dev10_target.py",
        "dev11_cache_target.py",
        "dev11_browser_service.py",
    ):
        shutil.copy2(ROOT / "tools/gateway/evidence" / name, build / "service/gateway" / name)
    local = build / "service/local"
    local.mkdir()
    for source, name in (
        ("deploy/local/local_service.py", "local_service.py"),
        ("deploy/local/initialize_credentials.py", "initialize_credentials.py"),
        ("deploy/local/socket_lease.py", "socket_lease.py"),
        ("tests/development_slice/request.json", "request.json"),
        ("tests/tool_cycle/scenarios.json", "scenarios.json"),
    ):
        shutil.copy2(ROOT / source, local / name)
    web = build / "service/web"
    copy_web_assets(ROOT / "web", web)
    # Disposable installed-client actors for the DEV-07 target matrix use the
    # current SDK sources, packaged offline by the context builder.
    shutil.copy2(
        ROOT / "tools/gateway/evidence/dev07_actor.py", build / "python/actors/dev07_actor.py"
    )
    shutil.copy2(
        ROOT / "tools/gateway/evidence/dev07_actor.cjs", build / "js/actors/dev07_actor.cjs"
    )
    ingress = build / "ingress"
    ingress.mkdir()
    shutil.copy2(ROOT / "deploy/local/console_ingress.py", ingress / "console_ingress.py")
    shutil.copy2(
        ROOT / "server/src/ezllmrouter_server/runtime_resources.py",
        ingress / "runtime_resources.py",
    )
    service_client = build / "service/client"
    service_client.mkdir()
    shutil.copy2(wheel, service_client / DEV09_CLIENT)
    client_metadata = service_client / "metadata.json"
    client_metadata.write_text(
        json.dumps({"distribution": PYTHON_CLIENT["name"], "version": PYTHON_CLIENT["version"]})
        + "\n",
        encoding="utf-8",
    )
    client_digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    (build / "service/client-wheel.sha256").write_text(
        f"{client_digest}  /opt/ezllmrouter/client/{DEV09_CLIENT}\n"
        + f"{hashlib.sha256(client_metadata.read_bytes()).hexdigest()}  /opt/ezllmrouter/client/metadata.json\n"
    )
    target_tests = build / "service/tests/operator_console"
    target_tests.mkdir(parents=True)
    (build / "service/tests/__init__.py").write_text("")
    (target_tests / "__init__.py").write_text("")
    for name in (
        "test_attribution.py",
        "test_reporting.py",
        "test_report_http.py",
        "test_registry_core.py",
        "dev09_accounting_fixture.json",
    ):
        shutil.copy2(ROOT / "tests/operator_console" / name, target_tests / name)
    for relative in (
        "development_slice/request.json",
        "development_slice/fixture.json",
    ):
        target = build / "service/tests" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "tests" / relative, target)
    shutil.copy2(
        ROOT / "deploy/local/dev09_migration_check.py",
        build / "service/gateway/dev09_migration_check.py",
    )
    shutil.copy2(
        ROOT / "tools/operator/dev09_python_actor.py",
        build / "service/local/dev09_python_actor.py",
    )
    dev09_js = build / "dev09_js"
    dev09_js.mkdir()
    shutil.copy2(ROOT / "deploy/local/Dockerfile.dev09-js", dev09_js / "Dockerfile")
    shutil.copy2(ROOT / "tools/operator/dev09_js_actor.cjs", dev09_js / "dev09_js_actor.cjs")
    shutil.copy2(
        ROOT / "tools/gateway/evidence/dev10_js_actor.cjs", dev09_js / "dev10_js_actor.cjs"
    )
    subprocess.run(
        ("npm", "pack", "--offline", "--pack-destination", str(sdk_out), "./clients/js"),
        check=True,
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        timeout=900,
    )
    js_package = sdk_out / JS_ARCHIVE
    if not js_package.is_file() or package_artifacts(sdk_out) != {DEV09_CLIENT, js_package.name}:
        raise RuntimeError("offline DEV-09 CommonJS package mismatch")
    shutil.copy2(js_package, dev09_js / "client.tgz")
    js_metadata = dev09_js / "client-metadata.json"
    js_metadata.write_text(
        json.dumps({"name": JS_CLIENT["name"], "version": JS_CLIENT["version"]}) + "\n",
        encoding="utf-8",
    )
    js_digest = hashlib.sha256(js_package.read_bytes()).hexdigest()
    (dev09_js / "client.tgz.sha256").write_text(
        f"{js_digest}  /opt/ezllmrouter/client.tgz\n"
        + f"{hashlib.sha256(js_metadata.read_bytes()).hexdigest()}  /opt/ezllmrouter/client-metadata.json\n"
    )
    identity = {
        "commit": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "dirty": source_dirty(),
        "fingerprint": source_hash,
        "prepared_at": datetime.now(timezone.utc).isoformat(),
    }
    (local / "build-identity.json").write_text(json.dumps(identity, indent=2) + "\n")
    overlays = [
        build / "service/Dockerfile",
        build / "service/gateway/dev07_target_preflight.py",
        build / "service/gateway/dev08_integrated.py",
        build / "service/gateway/dev08_tls_receiver.py",
        build / "service/gateway/dev10_target.py",
        build / "service/gateway/dev11_cache_target.py",
        build / "service/gateway/dev11_browser_service.py",
        build / "worker/Dockerfile",
        build / "worker/local_worker.py",
        build / "worker/socket_lease.py",
        *(local.iterdir()),
        *(web.iterdir()),
        *(ingress.iterdir()),
        build / "python/actors/dev07_actor.py",
        build / "js/actors/dev07_actor.cjs",
        *(service_client.iterdir()),
        build / "service/client-wheel.sha256",
        build / "service/gateway/dev09_migration_check.py",
        build / "service/local/dev09_python_actor.py",
        *(p for p in dev09_js.iterdir() if p.is_file()),
        *(p for p in (build / "service/tests").rglob("*") if p.is_file()),
    ]
    manifest = {
        "kind": "DEV-06 local profile staging",
        "fingerprint": source_hash,
        "commit": identity["commit"],
        "dirty": identity["dirty"],
        "build_dir": str(run / "build"),
        "artifact_root": str(artifact),
        "dev09_client_reuse": reused_client,
        "source_packet": str(run / source_packet),
        "dev09_client_wheel_sha256": client_digest,
        "dev09_commonjs_tarball_sha256": js_digest,
        "overlays": [
            {
                "path": str(p.relative_to(build)),
                "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in sorted(overlays)
        ],
    }
    (work / "LOCAL-BUILD-MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if run.exists():
        raise RuntimeError("staging fingerprint collision: " + str(run))
    work.rename(run)
    (STATE / "current-build.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
