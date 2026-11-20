"""Hash-checked, minimal DEV-04 Docker contexts and source snapshot."""

from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile


CLIENT_DEPS = {"anyio", "certifi", "h11", "httpcore", "httpx", "idna", "typing-extensions"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_clients(root, destination):
    """Build current client sources offline instead of relying on retired SDK archives."""
    python = tomllib.loads((root / "clients/python/pyproject.toml").read_text())["project"]
    javascript = json.loads((root / "clients/js/package.json").read_text())
    wheel = re.sub(r"[-_.]+", "_", python["name"]) + "-" + python["version"] + "-py3-none-any.whl"
    tarball = (
        javascript["name"].lstrip("@").replace("/", "-") + "-" + javascript["version"] + ".tgz"
    )
    destination.mkdir(parents=True)
    subprocess.run(
        [
            "uv",
            "build",
            "--offline",
            "--wheel",
            str(root / "clients/python"),
            "-o",
            str(destination),
        ],
        check=True,
        cwd=root,
        stdout=subprocess.DEVNULL,
    )
    subprocess.run(
        ["npm", "pack", "--offline", "--pack-destination", str(destination), "./clients/js"],
        check=True,
        cwd=root,
        stdout=subprocess.DEVNULL,
    )
    if {p.name for p in destination.iterdir() if p.name != ".gitignore"} != {wheel, tarball}:
        raise ValueError("unexpected current client package inventory")
    return python, destination / wheel, destination / tarball


def verify_lock_inventory(lock, wheels):
    rows = {}
    for line in lock.read_text().splitlines():
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^ ]+) --hash=sha256:([0-9a-f]{64})", line)
        if match is None:
            raise ValueError("invalid frozen gateway lock entry: " + line)
        name, version, digest = match.groups()
        name = name.lower().replace("_", "-").replace(".", "-")
        if name in rows:
            raise ValueError("duplicate frozen gateway lock entry: " + name)
        rows[name] = (version, digest)
    expected = {
        row["name"].lower().replace("_", "-").replace(".", "-"): (row["version"], row["sha256"])
        for row in wheels
    }
    if len(expected) != len(wheels):
        raise ValueError("duplicate frozen gateway inventory entry")
    if rows != expected:
        names = sorted(
            name for name in rows.keys() | expected.keys() if rows.get(name) != expected.get(name)
        )
        raise ValueError("frozen gateway lock/inventory mismatch: " + ", ".join(names))


def source_mapping(root, dev05=False, *, fixtures=False):
    source_files = [
        ("tests/gateway_integration/run.sh", "harness/run.sh"),
        ("tests/gateway_integration/boundary_steps.sh", "harness/boundary_steps.sh"),
        ("tests/gateway_integration/choice_b_steps.sh", "harness/choice_b_steps.sh"),
        ("tests/gateway_integration/compose.yaml", "harness/compose.yaml"),
        ("tools/gateway/stage.py", "harness/stage.py"),
        ("tools/gateway/evidence/receipts.py", "harness/receipts.py"),
        ("tools/gateway/evidence/review_gate.py", "harness/review_gate.py"),
        ("tools/gateway/evidence/source_correspondence.py", "harness/source_correspondence.py"),
        ("tools/gateway/evidence/verify_runtime.py", "harness/verify_runtime.py"),
        ("tests/gateway_integration/correlate_partial.py", "harness/correlate_partial.py"),
        ("tests/gateway_integration/verify_boundary.py", "harness/verify_boundary.py"),
        ("tests/gateway_integration/verify_choice_b.py", "harness/verify_choice_b.py"),
        (
            "tests/gateway_integration/verify_choice_b_freshness.py",
            "harness/verify_choice_b_freshness.py",
        ),
        ("tests/gateway_integration/test_core_bridge.py", "harness/test_core_bridge.py"),
        ("tests/gateway_integration/test_model_identity.py", "harness/test_model_identity.py"),
        ("tests/gateway_integration/test_readiness.py", "harness/test_readiness.py"),
        ("tests/gateway_integration/test_choice_b.py", "harness/test_choice_b.py"),
        (
            "tests/gateway_integration/test_owned_sender_transport.py",
            "harness/test_owned_sender_transport.py",
        ),
        (
            "tests/gateway_integration/test_run10_held_timeout.py",
            "harness/test_run10_held_timeout.py",
        ),
        (
            "tests/gateway_integration/inputs/litellm_completion_timeout_1_105_1.py",
            "harness/litellm_completion_timeout_1_105_1.py",
        ),
        ("tests/gateway_integration/test_retry_cause.py", "service/gateway/test_retry_cause.py"),
        ("tests/gateway_integration/test_alt_handler.py", "service/gateway/test_alt_handler.py"),
        ("tests/gateway_integration/verify_actor_output.py", "harness/verify_actor_output.py"),
        ("tests/gateway_integration/Dockerfile.service", "service/Dockerfile"),
        ("tests/gateway_integration/Dockerfile.worker", "worker/Dockerfile"),
        ("tests/gateway_integration/Dockerfile.receiver", "receiver/Dockerfile"),
        ("tests/gateway_integration/Dockerfile.python-consumer", "python/Dockerfile"),
        ("tests/gateway_integration/Dockerfile.js-consumer", "js/Dockerfile"),
        ("tools/gateway/compat/guard.py", "service/gateway/guard.py"),
        ("tests/gateway_integration/test_guard.py", "service/gateway/test_guard.py"),
        ("tools/gateway/compat/adapter.py", "service/gateway/adapter.py"),
        ("tools/gateway/compat/choice_b_sender.py", "service/gateway/choice_b_sender.py"),
        (
            "tools/gateway/compat/owned_sender_transport.py",
            "service/gateway/owned_sender_transport.py",
        ),
        (
            "tools/gateway/compat/owned_tls_sender_transport.py",
            "service/gateway/owned_tls_sender_transport.py",
        ),
        ("tools/gateway/choice_b_service.py", "service/gateway/choice_b_service.py"),
        (
            "server/src/ezllmrouter_server/gateway/choice_b_wire.py",
            "service/gateway/choice_b_wire.py",
        ),
        ("server/src/ezllmrouter_server/gateway/choice_b_wire.py", "worker/choice_b_wire.py"),
        ("worker/choice_b_worker.py", "worker/choice_b_worker.py"),
        ("server/src/ezllmrouter_server/observability.py", "worker/worker_logging.py"),
        ("server/src/ezllmrouter_server/runtime_resources.py", "worker/runtime_resources.py"),
        ("tools/gateway/compat/proxy_recipe.py", "service/gateway/proxy_recipe.py"),
        ("tools/gateway/service_main.py", "service/gateway/service_main.py"),
        ("tools/gateway/receiver.py", "receiver/receiver.py"),
        ("tests/gateway_integration/python_text.py", "python/actors/python_text.py"),
        ("tests/gateway_integration/python_negative.py", "python/actors/python_negative.py"),
        ("tests/gateway_integration/python_boundary.py", "python/actors/python_boundary.py"),
        ("tests/gateway_integration/python_wait.py", "python/actors/python_wait.py"),
        ("tests/gateway_integration/js_text.cjs", "js/actors/js_text.cjs"),
        (
            "tests/gateway_integration/actor_output_regression.cjs",
            "js/actors/actor_output_regression.cjs",
        ),
        ("tests/tool_cycle/python_actor.py", "python/actors/python_actor.py"),
        ("tests/tool_cycle/scenarios.json", "python/actors/scenarios.json"),
        ("tests/tool_cycle/js_actor.cjs", "js/actors/js_actor.cjs"),
        ("tests/tool_cycle/scenarios.json", "js/actors/scenarios.json"),
        ("tests/development_slice/request.json", "python/actors/request.json"),
        ("tests/development_slice/request.json", "js/actors/request.json"),
        ("tests/development_slice/request.json", "service/dev_slice/request.json"),
        ("tests/development_slice/fixture.json", "service/dev_slice/fixture.json"),
        ("tools/gateway/compat/recipe.py", "service/dev_slice/recipe.py"),
    ]
    if fixtures:
        source_files.extend(
            [
                ("tools/gateway/fixture_adapters.py", "service/gateway/fixture_adapters.py"),
                ("tools/gateway/service_fixture.py", "service/gateway/service_fixture.py"),
                ("tools/gateway/worker_fixture.py", "worker/fixture/worker_fixture.py"),
            ]
        )
    server_source = root / "server/src"
    for package in ("ezllmrouter_server",):
        source_files.extend(
            (str(path.relative_to(root)), "service/server/" + str(path.relative_to(server_source)))
            for path in sorted((server_source / package).rglob("*"))
            if path.is_file() and path.suffix in {".py", ".json", ".sql"}
        )
    if dev05:
        source_files = [
            ("tests/gateway_integration/dev05_fixture.json", target)
            if target == "service/dev_slice/fixture.json"
            else (source, target)
            for source, target in source_files
        ]
        source_files.extend(
            [
                ("tests/gateway_integration/dev05_steps.sh", "harness/dev05_steps.sh"),
                ("tools/gateway/compat/worker_ready.py", "service/gateway/worker_ready.py"),
                ("tests/gateway_integration/test_worker_ready.py", "harness/test_worker_ready.py"),
                ("tools/gateway/evidence/capture_runtime.py", "harness/capture_runtime.py"),
                ("tools/gateway/evidence/verify_dev05.py", "harness/verify_dev05.py"),
                ("tools/gateway/evidence/scan_dev05_logs.py", "harness/scan_dev05_logs.py"),
                ("tests/gateway_integration/test_dev05.py", "harness/test_dev05.py"),
                (
                    "tests/gateway_integration/test_work_identity.py",
                    "service/gateway/test_work_identity.py",
                ),
                (
                    "tests/gateway_integration/test_dev05_capture.py",
                    "harness/test_dev05_capture.py",
                ),
                (
                    "tests/gateway_integration/test_dev05_python_actor.py",
                    "harness/test_dev05_python_actor.py",
                ),
                (
                    "tests/gateway_integration/test_dev05_js_actor.cjs",
                    "harness/test_dev05_js_actor.cjs",
                ),
                ("tests/tool_cycle/test_python_client.py", "python/actors/test_python_client.py"),
                ("tests/tool_cycle/test_js_client.cjs", "js/actors/test_js_client.cjs"),
                (
                    "tests/fixtures/contracts/wp-a-03-c01/EZLLMROUTER-WP-A-VECTORS-v0.3-CORRECTION-01.json",
                    "python/actors/vectors.json",
                ),
                (
                    "tests/fixtures/contracts/wp-a-03-c01/EZLLMROUTER-WP-A-VECTORS-v0.3-CORRECTION-01.json",
                    "js/actors/vectors.json",
                ),
            ]
        )
    return source_files


def main():
    arguments = list(sys.argv[1:])
    fixtures = "--fixtures" in arguments
    if fixtures:
        arguments.remove("--fixtures")
    if len(arguments) not in (2, 3, 4):
        raise SystemExit("usage: stage.py ROOT RUN_DIR [SOURCE_OUTPUT_DIR [DEV-05]] [--fixtures]")
    root, run = map(Path, arguments[:2])
    source_output = Path(arguments[2]) if len(arguments) >= 3 else root / ".artifacts/gateway"
    dev05 = len(arguments) == 4 and arguments[3] == "DEV-05"
    if len(arguments) == 4 and not dev05:
        raise ValueError("unsupported source packet prefix")
    build = run / "build"
    if build.exists():
        raise ValueError("build context collision")
    artifact_root = os.environ.get("EZLLMROUTER_ARTIFACT_ROOT")
    wheel_dir = (
        (Path(artifact_root) / "inputs/gateway-inputs/dev04/wheels")
        if artifact_root
        else root / "gateway-inputs/dev04/wheels"
    )
    inventory = json.loads((root / "deploy/local/inputs/gateway/WHEEL-INVENTORY.json").read_text())
    wheels = inventory["wheels"]
    if len(wheels) != 117:
        raise ValueError("unexpected wheel count")
    verify_lock_inventory(root / "deploy/local/inputs/gateway/requirements.gateway.lock", wheels)
    for row in wheels:
        path = wheel_dir / row["filename"]
        if not path.is_file() or path.stat().st_size != row["bytes"] or sha(path) != row["sha256"]:
            raise ValueError("wheel mismatch: " + row["filename"])
    if {path.name for path in wheel_dir.glob("*.whl")} != {row["filename"] for row in wheels}:
        raise ValueError("unexpected wheel in input directory")
    source_files = source_mapping(root, dev05, fixtures=fixtures)
    rows = []
    for source, target in source_files:
        src, dest = root / source, build / target
        if not src.is_file():
            raise ValueError("missing executed source: " + source)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        rows.append(
            {"source": source, "target": target, "bytes": dest.stat().st_size, "sha256": sha(dest)}
        )
    for row in wheels:
        dest = build / "service/wheels" / row["filename"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(wheel_dir / row["filename"], dest)
        worker_dest = build / "worker/wheels" / row["filename"]
        worker_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(wheel_dir / row["filename"], worker_dest)
    (build / "service/wheelhouse.sha256").write_text(
        "".join(f"{row['sha256']}  {row['filename']}\n" for row in wheels)
    )
    shutil.copy2(build / "service/wheelhouse.sha256", build / "worker/wheelhouse.sha256")
    shutil.copy2(
        root / "deploy/local/inputs/gateway/requirements.gateway.lock",
        build / "service/requirements.gateway.lock",
    )
    shutil.copy2(
        root / "deploy/local/inputs/gateway/requirements.gateway.lock",
        build / "worker/requirements.gateway.lock",
    )
    client_rows = [row for row in wheels if row["name"].lower().replace("_", "-") in CLIENT_DEPS]
    if len(client_rows) != 7:
        raise ValueError("client HTTPX closure mismatch")
    client, client_source, js_source = build_clients(root, run / "client-packages")
    client_wheel_dir = build / "python/wheels"
    client_wheel_dir.mkdir(parents=True)
    for row in client_rows:
        shutil.copy2(wheel_dir / row["filename"], client_wheel_dir / row["filename"])
    shutil.copy2(client_source, client_wheel_dir / client_source.name)
    shutil.copy2(js_source, build / "js/client.tgz")
    all_client = [
        *client_rows,
        {
            "name": client["name"],
            "version": client["version"],
            "filename": client_source.name,
            "sha256": sha(client_source),
        },
    ]
    (build / "python/wheelhouse.sha256").write_text(
        "".join(f"{row['sha256']}  {row['filename']}\n" for row in all_client)
    )
    (build / "python/requirements.client.lock").write_text(
        "".join(
            f"{row['name']}=={row['version']} --hash=sha256:{row['sha256']}\n" for row in all_client
        )
    )
    manifest = {
        "source_files": rows,
        "gateway_wheels": len(wheels),
        "gateway_wheel_bytes": sum(row["bytes"] for row in wheels),
        "client_artifacts": {
            client_source.name: sha(client_source),
            js_source.name: sha(js_source),
        },
    }
    (run / "source-build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    source_output.mkdir(parents=True, exist_ok=True, mode=0o700)
    source_zip = source_output / f"{'DEV-05' if dev05 else 'DEV-04'}-SOURCE-{run.name}.zip"
    if source_zip.exists():
        raise ValueError("source packet collision")
    with zipfile.ZipFile(source_zip, "x", zipfile.ZIP_DEFLATED) as archive:
        for row in rows:
            archive.write(build / row["target"], row["target"])
        archive.writestr("SOURCE-MANIFEST.json", json.dumps(manifest, indent=2))
    print(
        json.dumps(
            {
                "source_packet": str(source_zip),
                "sha256": sha(source_zip),
                "source_files": len(rows),
                "wheels": len(wheels),
            }
        )
    )


if __name__ == "__main__":
    main()
