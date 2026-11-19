"""Hash checked, offline DEV-03 Docker contexts from local approved inputs."""
from pathlib import Path
import hashlib
import json
import shutil
import sys


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy(src, dst, expected=None):
    if not src.is_file() or src.is_symlink() or dst.exists() or dst.is_symlink():
        raise ValueError(f"missing, linked or colliding input: {src} -> {dst}")
    if expected and sha(src) != expected:
        raise ValueError(f"input hash mismatch: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    if sha(src) != sha(dst):
        raise ValueError(f"staged hash mismatch: {src}")
    return {"source": str(src), "target": str(dst), "bytes": dst.stat().st_size, "sha256": sha(dst)}


def prepare(root, run):
    root, run = Path(root).resolve(), Path(run).resolve()
    predecessor = Path("/private/tmp/ezllmrouter-dev-01/run-20261018-04")
    manifest = json.loads((predecessor / "wheel-manifest.json").read_text())
    py_lock = json.loads((root / "tests/client_parity/wheelhouse.lock.json").read_text())["wheels"]
    by_name = {x["filename"]: x for x in manifest}
    if len(py_lock) != 7 or len(by_name) != len(manifest):
        raise ValueError("predecessor wheel set changed")
    rows = []
    for entry in py_lock:
        if by_name.get(entry["filename"]) != {k: entry[k] for k in ("filename", "bytes", "sha256")}:
            raise ValueError("Python wheel receipt mismatch")
        src = predecessor / "wheels" / entry["filename"]
        if src.stat().st_size != entry["bytes"]:
            raise ValueError("Python wheel size mismatch")
        rows.append(copy(src, run / "build/python/wheels" / src.name, entry["sha256"]))
    (run / "build/python/wheelhouse.sha256").write_text(
        "".join(f"{x['sha256']}  {Path(x['target']).name}\n" for x in rows))
    for entry in manifest:
        src = predecessor / "wheels" / entry["filename"]
        if src.stat().st_size != entry["bytes"]:
            raise ValueError("service wheel size mismatch")
        rows.append(copy(src, run / "build/service/wheels" / src.name, entry["sha256"]))
    for name, target in (("cognitivedynamics_ezllmrouter_client-0.3.0-py3-none-any.whl", "python"),
                         ("cognitivedynamics-ezllmrouter-client-0.3.0.tgz", "js")):
        rows.append(copy(root / "docs/development/dev-03" / name, run / "build" / target / name))
    for name, target in (("python_actor.py", "python"), ("js_actor.cjs", "js"),
                         ("test_python_client.py", "python"), ("test_js_client.cjs", "js")):
        rows.append(copy(root / "tests/tool_cycle" / name, run / "build" / target / "tests" / name))
    for target in ("python", "js"):
        rows.append(copy(root / "tests/development_slice/request.json", run / "build" / target / "tests/request.json"))
        rows.append(copy(root / "tests/tool_cycle/scenarios.json", run / "build" / target / "tests/scenarios.json"))
        rows.append(copy(root / "tests/fixtures/contracts/wp-a-03-c01/EZLLMROUTER-WP-A-VECTORS-v0.3-CORRECTION-01.json",
                         run / "build" / target / "tests/vectors.json"))
    for src in sorted((root / "server/src").rglob("*")):
        if src.is_dir() or "__pycache__" in src.parts or src.name == ".DS_Store":
            continue
        rows.append(copy(src, run / "build/service/server" / src.relative_to(root / "server/src")))
    for name in ("service_main.py", "synthetic_routes.py", "native_adapter.py", "recipe.py", "fixture.json",
                 "request.json", "test_crypto.py", "test_http.py", "test_native_adapter.py"):
        rows.append(copy(root / "tests/development_slice" / name, run / "build/service/tests" / name))
    rows.append(copy(root / "tests/tool_cycle/scenarios.json", run / "build/service/tests/scenarios.json"))
    for name in ("test_core.py", "scenarios.json"):
        rows.append(copy(root / "tests/tool_cycle" / name,
                         run / "build/service/tests/tool_cycle" / name))
    for name in ("fixture.json", "request.json", "recipe.py"):
        rows.append(copy(root / "tests/development_slice" / name,
                         run / "build/service/tests/development_slice" / name))
    rows.append(copy(root / "tests/development_slice/requirements.lock", run / "build/service/requirements.lock"))
    rows.append(copy(root / "tests/development_slice/receiver.py", run / "build/receiver/receiver.py"))
    for name in ("compose.yaml", "Dockerfile.python-consumer", "Dockerfile.js-consumer", "run.sh",
                 "stage.py", "README.md", "test_core.py", "test_receiver.py"):
        src = root / "tests/tool_cycle" / name
        if not src.is_file() or src.is_symlink():
            raise ValueError(f"missing source: {src}")
        rows.append({"source": str(src), "bytes": src.stat().st_size, "sha256": sha(src)})
    for name in ("Dockerfile.service", "Dockerfile.receiver"):
        src = root / "tests/development_slice" / name
        rows.append({"source": str(src), "bytes": src.stat().st_size, "sha256": sha(src)})
    # The runner's private umask protects scratch, but COPY retains context
    # directory modes. Make only the staged, nonsensitive build contexts
    # traversable by the images' declared non-root users.
    for role in ("python", "js", "service", "receiver"):
        context = run / "build" / role
        for directory in (context, *(p for p in context.rglob("*") if p.is_dir())):
            directory.chmod(0o755)
    output = run / "source-build-manifest.json"
    output.write_text(json.dumps({"rows": rows, "self_excluded": True}, indent=2) + "\n")
    print(json.dumps({"stage_rows": len(rows), "source_manifest_sha256": sha(output)}))


def verify_images(path):
    images = json.loads(Path(path).read_text())
    if len(images) != 2 or any(x.get("Os") != "linux" or x.get("Architecture") != "arm64" for x in images):
        raise ValueError("pinned Linux ARM64 bases unavailable")
    print(json.dumps({"base_image_ids": [x["Id"] for x in images], "os": "linux", "arch": "arm64"}))


if __name__ == "__main__":
    if sys.argv[1] == "prepare" and len(sys.argv) == 4:
        prepare(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "verify-images" and len(sys.argv) == 3:
        verify_images(sys.argv[2])
    else:
        raise SystemExit("usage: stage.py prepare ROOT RUN | verify-images INSPECT_JSON")
