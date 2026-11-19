"""Hash-checked, minimal DEV-04 Docker contexts and source snapshot."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import sys
import zipfile


CLIENT_WHEEL = "mach33_duranki_client-0.0.3-py3-none-any.whl"
CLIENT_WHEEL_SHA = "efabf2ee4832b627b104845b79bf0302f1b7448f17c2c4ef8c35b8287d8fac57"
CLIENT_TARBALL = "mach33-duranki-client-0.0.2.tgz"
CLIENT_TARBALL_SHA = "5672be3e0c5ed7e847e508f22ef269d83c04bb65c830dba47e923055ec93ec82"
CLIENT_DEPS = {"anyio", "certifi", "h11", "httpcore", "httpx", "idna", "typing-extensions"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    expected = {row["name"].lower().replace("_", "-").replace(".", "-"):
                (row["version"], row["sha256"]) for row in wheels}
    if len(expected) != len(wheels):
        raise ValueError("duplicate frozen gateway inventory entry")
    if rows != expected:
        names = sorted(name for name in rows.keys() | expected.keys()
                       if rows.get(name) != expected.get(name))
        raise ValueError("frozen gateway lock/inventory mismatch: " + ", ".join(names))


def source_mapping(root, dev05=False):
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
        ("tests/gateway_integration/verify_choice_b_freshness.py", "harness/verify_choice_b_freshness.py"),
        ("tests/gateway_integration/test_core_bridge.py", "harness/test_core_bridge.py"),
        ("tests/gateway_integration/test_model_identity.py", "harness/test_model_identity.py"),
        ("tests/gateway_integration/test_readiness.py", "harness/test_readiness.py"),
        ("tests/gateway_integration/test_choice_b.py", "harness/test_choice_b.py"),
        ("tests/gateway_integration/test_owned_sender_transport.py", "harness/test_owned_sender_transport.py"),
        ("tests/gateway_integration/test_run10_held_timeout.py", "harness/test_run10_held_timeout.py"),
        ("tests/gateway_integration/inputs/litellm_completion_timeout_1_105_1.py", "harness/litellm_completion_timeout_1_105_1.py"),
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
        ("tools/gateway/compat/owned_sender_transport.py", "service/gateway/owned_sender_transport.py"),
        ("tools/gateway/compat/owned_tls_sender_transport.py", "service/gateway/owned_tls_sender_transport.py"),
        ("tools/gateway/choice_b_service.py", "service/gateway/choice_b_service.py"),
        ("server/src/duranki_server/gateway/choice_b_wire.py", "service/gateway/choice_b_wire.py"),
        ("server/src/duranki_server/gateway/choice_b_wire.py", "worker/choice_b_wire.py"),
        ("worker/choice_b_worker.py", "worker/choice_b_worker.py"),
        ("tools/gateway/compat/proxy_recipe.py", "service/gateway/proxy_recipe.py"),
        ("tools/gateway/service_main.py", "service/gateway/service_main.py"),
        ("tools/gateway/receiver.py", "receiver/receiver.py"),
        ("tests/gateway_integration/python_text.py", "python/actors/python_text.py"),
        ("tests/gateway_integration/python_negative.py", "python/actors/python_negative.py"),
        ("tests/gateway_integration/python_boundary.py", "python/actors/python_boundary.py"),
        ("tests/gateway_integration/python_wait.py", "python/actors/python_wait.py"),
        ("tests/gateway_integration/js_text.cjs", "js/actors/js_text.cjs"),
        ("tests/gateway_integration/actor_output_regression.cjs", "js/actors/actor_output_regression.cjs"),
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
    server_source = root / "server/src/duranki_server"
    source_files.extend((str(path.relative_to(root)),
                         "service/server/duranki_server/" + str(path.relative_to(server_source)))
                        for path in sorted(server_source.rglob("*"))
                        if path.is_file() and path.suffix in {".py", ".json"})
    if dev05:
        source_files = [("tests/gateway_integration/dev05_fixture.json", target)
                        if target == "service/dev_slice/fixture.json" else (source, target)
                        for source, target in source_files]
        source_files.extend([
            ("tests/gateway_integration/dev05_steps.sh", "harness/dev05_steps.sh"),
            ("tools/gateway/compat/worker_ready.py", "service/gateway/worker_ready.py"),
            ("tests/gateway_integration/test_worker_ready.py", "harness/test_worker_ready.py"),
            ("tools/gateway/evidence/capture_runtime.py", "harness/capture_runtime.py"),
            ("tools/gateway/evidence/verify_dev05.py", "harness/verify_dev05.py"),
            ("tools/gateway/evidence/scan_dev05_logs.py", "harness/scan_dev05_logs.py"),
            ("tests/gateway_integration/test_dev05.py", "harness/test_dev05.py"),
            ("tests/gateway_integration/test_work_identity.py", "service/gateway/test_work_identity.py"),
            ("tests/gateway_integration/test_dev05_capture.py", "harness/test_dev05_capture.py"),
            ("tests/gateway_integration/test_dev05_python_actor.py", "harness/test_dev05_python_actor.py"),
            ("tests/gateway_integration/test_dev05_js_actor.cjs", "harness/test_dev05_js_actor.cjs"),
            ("tests/tool_cycle/test_python_client.py", "python/actors/test_python_client.py"),
            ("tests/tool_cycle/test_js_client.cjs", "js/actors/test_js_client.cjs"),
            ("docs/contracts/wp-a-03-c01/DURANKI-WP-A-VECTORS-v0.3-CORRECTION-01.json",
             "python/actors/vectors.json"),
            ("docs/contracts/wp-a-03-c01/DURANKI-WP-A-VECTORS-v0.3-CORRECTION-01.json",
             "js/actors/vectors.json"),
        ])
    return source_files


def main():
    if len(sys.argv) not in (3, 4, 5):
        raise SystemExit("usage: stage.py ROOT RUN_DIR [SOURCE_OUTPUT_DIR [DEV-05]]")
    root, run = map(Path, sys.argv[1:3])
    source_output = Path(sys.argv[3]) if len(sys.argv) >= 4 else root / "docs/development/dev-04"
    dev05 = len(sys.argv) == 5 and sys.argv[4] == "DEV-05"
    if len(sys.argv) == 5 and not dev05:
        raise ValueError("unsupported source packet prefix")
    build = run / "build"
    if build.exists():
        raise ValueError("build context collision")
    artifact_root = os.environ.get("DURANKI_ARTIFACT_ROOT")
    wheel_dir = ((Path(artifact_root) / "inputs/gateway-inputs/dev04/wheels")
                 if artifact_root else root / "gateway-inputs/dev04/wheels")
    inventory = json.loads((root / "docs/development/dev-04/WHEEL-INVENTORY.json").read_text())
    wheels = inventory["wheels"]
    if len(wheels) != 117:
        raise ValueError("unexpected wheel count")
    verify_lock_inventory(root / "docs/development/dev-04/requirements.gateway.lock", wheels)
    for row in wheels:
        path = wheel_dir / row["filename"]
        if not path.is_file() or path.stat().st_size != row["bytes"] or sha(path) != row["sha256"]:
            raise ValueError("wheel mismatch: " + row["filename"])
    if {path.name for path in wheel_dir.glob("*.whl")} != {row["filename"] for row in wheels}:
        raise ValueError("unexpected wheel in input directory")
    source_files = source_mapping(root, dev05)
    rows = []
    for source, target in source_files:
        src, dest = root / source, build / target
        if not src.is_file():
            raise ValueError("missing executed source: " + source)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        rows.append({"source": source, "target": target, "bytes": dest.stat().st_size,
                     "sha256": sha(dest)})
    for row in wheels:
        dest = build / "service/wheels" / row["filename"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(wheel_dir / row["filename"], dest)
        worker_dest = build / "worker/wheels" / row["filename"]
        worker_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(wheel_dir / row["filename"], worker_dest)
    (build / "service/wheelhouse.sha256").write_text(
        "".join(f"{row['sha256']}  {row['filename']}\n" for row in wheels))
    shutil.copy2(build / "service/wheelhouse.sha256", build / "worker/wheelhouse.sha256")
    shutil.copy2(root / "docs/development/dev-04/requirements.gateway.lock",
                 build / "service/requirements.gateway.lock")
    shutil.copy2(root / "docs/development/dev-04/requirements.gateway.lock",
                 build / "worker/requirements.gateway.lock")
    client_rows = [row for row in wheels if row["name"].lower().replace("_", "-") in CLIENT_DEPS]
    if len(client_rows) != 7:
        raise ValueError("client HTTPX closure mismatch")
    client_input = ((Path(artifact_root) / "inputs/tests/gateway_integration/inputs")
                    if artifact_root else root / "tests/gateway_integration/inputs")
    client_source = client_input / CLIENT_WHEEL
    js_source = client_input / CLIENT_TARBALL
    if sha(client_source) != CLIENT_WHEEL_SHA or sha(js_source) != CLIENT_TARBALL_SHA:
        raise ValueError("reviewed client artifact mismatch")
    client_wheel_dir = build / "python/wheels"
    client_wheel_dir.mkdir(parents=True)
    for row in client_rows:
        shutil.copy2(wheel_dir / row["filename"], client_wheel_dir / row["filename"])
    shutil.copy2(client_source, client_wheel_dir / CLIENT_WHEEL)
    shutil.copy2(js_source, build / "js/client.tgz")
    all_client = [*client_rows, {"name": "mach33-duranki-client", "version": "0.0.3",
                                 "filename": CLIENT_WHEEL, "sha256": CLIENT_WHEEL_SHA}]
    (build / "python/wheelhouse.sha256").write_text(
        "".join(f"{row['sha256']}  {row['filename']}\n" for row in all_client))
    (build / "python/requirements.client.lock").write_text(
        "".join(f"{row['name']}=={row['version']} --hash=sha256:{row['sha256']}\n"
                for row in all_client))
    manifest = {"source_files": rows, "gateway_wheels": len(wheels),
                "gateway_wheel_bytes": sum(row["bytes"] for row in wheels),
                "client_artifacts": {CLIENT_WHEEL: CLIENT_WHEEL_SHA,
                                     CLIENT_TARBALL: CLIENT_TARBALL_SHA}}
    (run / "source-build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    source_zip = source_output / f"{'DEV-05' if dev05 else 'DEV-04'}-SOURCE-{run.name}.zip"
    if source_zip.exists():
        raise ValueError("source packet collision")
    with zipfile.ZipFile(source_zip, "x", zipfile.ZIP_DEFLATED) as archive:
        for row in rows:
            archive.write(build / row["target"], row["target"])
        archive.writestr("SOURCE-MANIFEST.json", json.dumps(manifest, indent=2))
    print(json.dumps({"source_packet": str(source_zip), "sha256": sha(source_zip),
                      "source_files": len(rows), "wheels": len(wheels)}))


if __name__ == "__main__":
    main()
