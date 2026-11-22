"""Offline, hash-checked DEV-02 build-context preparation and image identity check."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.gateway.client_inputs import stage_fixture_inputs


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def regular(path):
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"missing or linked input: {path}")


def copy_checked(src, dst, expected=None):
    regular(src)
    if expected is not None and sha(src) != expected:
        raise ValueError(f"digest mismatch: {src}")
    if dst.exists() or dst.is_symlink():
        raise ValueError(f"output collision: {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    if sha(src) != sha(dst):
        raise ValueError(f"copy mismatch: {dst}")
    return {"source": str(src), "target": str(dst), "bytes": dst.stat().st_size, "sha256": sha(dst)}


def validate_corpus(root):
    cases = json.loads((root / "tests/client_parity/scenarios.json").read_text())["cases"]
    ids = [item["id"] for item in cases]
    keys = [(item["step_id"], item["execution_generation"]) for item in cases]
    if len(ids) != len(set(ids)) or len(keys) != len(set(keys)):
        raise ValueError("duplicate actor case identity")
    for item in cases:
        if (
            item.get("client") not in ("python", "js", "both")
            or type(item.get("wait_ms")) is not int
            or not 0 <= item["wait_ms"] <= 30000
            or item.get("receiver_delta") not in (0, 1)
        ):
            raise ValueError(f"incomplete actor case: {item['id']}")
        if item.get("expected_state") == "delivered":
            if type(item.get("expected_text")) is not str or not item["expected_text"]:
                raise ValueError(f"delivered case lacks expected text: {item['id']}")
        elif item.get("expected_state") == "pending":
            if (
                item.get("pending_result_policy")
                not in ("pollable_if_retained", "metadata_only_no_store")
                or item.get("total_timeout_ms") != 3000
                or item["wait_ms"] != 0
            ):
                raise ValueError(f"pending case lacks explicit budget or policy: {item['id']}")
            if item["pending_result_policy"] == "metadata_only_no_store" and (
                item.get("candidate_access_after"),
                item.get("result_unavailable_reason"),
            ) != ("not_retained", "wait_expired_no_store"):
                raise ValueError(f"no-store case lacks metadata expectation: {item['id']}")
        elif item.get("expected_error"):
            if item.get("failure_stage") not in ("before_transmit", "after_transmit"):
                raise ValueError(f"failure case lacks stage: {item['id']}")
        else:
            raise ValueError(f"case lacks result expectation: {item['id']}")
    return len(cases)


def prepare(root, run):
    root, run = Path(root).resolve(), Path(run).resolve()
    case_count = validate_corpus(root)
    lock = json.loads((root / "tests/client_parity/wheelhouse.lock.json").read_text())
    rows = stage_fixture_inputs(root, run, copy_checked)
    common = {
        "scenarios.json": root / "tests/client_parity/scenarios.json",
        "request.json": root / "tests/development_slice/request.json",
        "vectors.json": root
        / "tests/fixtures/contracts/wp-a-03-c01/EZLLMROUTER-WP-A-VECTORS-v0.3-CORRECTION-01.json",
    }
    python = {
        **common,
        "integration_python.py": root / "tests/client_parity/integration_python.py",
        "test_python_client.py": root / "tests/client_parity/test_python_client.py",
        "test_actor_logic.py": root / "tests/client_parity/test_actor_logic.py",
    }
    js = {
        **common,
        "integration_js.cjs": root / "tests/client_parity/integration_js.cjs",
        "test_actor_logic.cjs": root / "tests/client_parity/test_actor_logic.cjs",
        "test_client.cjs": root / "tests/development_slice/test_client.cjs",
    }
    for target, sources in (("python", python), ("js", js)):
        for name, src in sources.items():
            rows.append(copy_checked(src, run / "build" / target / "tests" / name))
    for src in sorted((root / "server/src").rglob("*")):
        if src.is_dir():
            continue
        if src.name == ".DS_Store" or "__pycache__" in src.parts:
            continue
        if src.is_symlink():
            raise ValueError(f"linked service source: {src}")
        rows.append(
            copy_checked(src, run / "build/service/server" / src.relative_to(root / "server/src"))
        )
    service_tests = (
        "service_main.py",
        "synthetic_routes.py",
        "native_adapter.py",
        "fixture.json",
        "request.json",
        "test_crypto.py",
        "test_http.py",
        "test_native_adapter.py",
    )
    for name in service_tests:
        rows.append(
            copy_checked(
                root / "tests/development_slice" / name, run / "build/service/tests" / name
            )
        )
    rows.append(
        copy_checked(
            root / "tests/tool_cycle/scenarios.json", run / "build/service/tests/scenarios.json"
        )
    )
    rows.append(
        copy_checked(
            root / "deploy/local/inputs/requirements.runtime.lock",
            run / "build/service/requirements.lock",
        )
    )
    for name in ("Dockerfile.python-consumer", "Dockerfile.js-consumer", "compose.yaml", "run.sh"):
        src = root / "tests/client_parity" / name
        regular(src)
        rows.append({"source": str(src), "bytes": src.stat().st_size, "sha256": sha(src)})
    src = root / "tests/development_slice/Dockerfile.service"
    regular(src)
    rows.append({"source": str(src), "bytes": src.stat().st_size, "sha256": sha(src)})
    (run / "source-build-manifest.json").write_text(json.dumps({"rows": rows}, indent=2))
    print(
        json.dumps(
            {
                "wheel_count": len(lock["wheels"]),
                "scenario_count": case_count,
                "staged_files": len(rows),
                "source_manifest_sha256": sha(run / "source-build-manifest.json"),
            }
        )
    )


def verify_images(root, inspect_path):
    root = Path(root).resolve()
    with zipfile.ZipFile(root / "docs/development/dev-01/DEV-01-RUNTIME-run-20261018-04.zip") as z:
        previous = json.loads(z.read("built-image-inspect.stdout"))
    expected = {x["RepoTags"][0]: x["Id"] for x in previous if x.get("RepoTags")}
    actual = json.loads(Path(inspect_path).read_text())
    for x in actual:
        tags = set(x.get("RepoTags") or [])
        matched = tags & expected.keys()
        if matched and (
            x["Id"] != expected[next(iter(matched))]
            or x["Os"] != "linux"
            or x["Architecture"] != "arm64"
        ):
            raise ValueError(f"reused image mismatch: {matched}")
    if not set(expected) <= {tag for x in actual for tag in (x.get("RepoTags") or [])}:
        raise ValueError("run-04 images missing")
    for x in actual:
        if x["Os"] != "linux" or x["Architecture"] != "arm64":
            raise ValueError("non-ARM64 image")
    print(json.dumps({"reused_run04_images": expected, "inspected_images": len(actual)}))


if __name__ == "__main__":
    if sys.argv[1] == "prepare":
        prepare(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "verify-images":
        verify_images(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit("usage: stage.py prepare root run | verify-images root inspect-json")
