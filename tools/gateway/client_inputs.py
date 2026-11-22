"""Stage current fixture SDKs and their reviewed offline wheel inputs."""

import json
import os
from pathlib import Path

from tools.gateway.frozen_inputs import verify_custody
from tools.gateway.stage import CLIENT_DEPS, build_clients


def stage_fixture_inputs(root, run, copy):
    configured = os.environ.get("EZLLMROUTER_ARTIFACT_ROOT")
    if not configured:
        raise ValueError("EZLLMROUTER_ARTIFACT_ROOT is required for reviewed fixture inputs")
    store = Path(configured).resolve()
    verify_custody(root, store)
    inventory = json.loads((root / "deploy/local/inputs/gateway/WHEEL-INVENTORY.json").read_text())
    frozen = {row["filename"]: row for row in inventory["wheels"]}
    client = json.loads((root / "tests/client_parity/wheelhouse.lock.json").read_text())
    expected = {
        row["filename"]
        for row in frozen.values()
        if row["name"].lower().replace("_", "-") in CLIENT_DEPS
    }
    if (
        client["wheel_count"] != 7
        or len(client["wheels"]) != 7
        or {row["filename"] for row in client["wheels"]} != expected
    ):
        raise ValueError("fixture client closure differs from frozen inputs")
    rows = []
    for item in client["wheels"]:
        name = item["filename"]
        reviewed = frozen[name]
        if any(item[key] != reviewed[key] for key in ("filename", "bytes", "sha256")):
            raise ValueError("fixture wheel identity differs from frozen inputs")
        rows.append(
            copy(
                store / "inputs/gateway-inputs/dev04/wheels" / name,
                run / "build/python/wheels" / name,
                item["sha256"],
            )
        )
    context = run / "build/python"
    (context / "wheelhouse.sha256").write_text(
        "".join(f"{item['sha256']}  {item['filename']}\n" for item in client["wheels"])
    )
    (context / "requirements.client.lock").write_text(
        "".join(
            f"{frozen[item['filename']]['name']}=={frozen[item['filename']]['version']} --hash=sha256:{item['sha256']}\n"
            for item in client["wheels"]
        )
    )
    runtime = (root / "deploy/local/inputs/requirements.runtime.lock").read_text().splitlines()
    by_pin = {
        row["name"].lower().replace("_", "-") + "==" + row["version"]: row
        for row in frozen.values()
    }
    for line in runtime:
        pin, hash_field = line.split()
        package, version = pin.split("==")
        item = by_pin[package.lower().replace("_", "-") + "==" + version]
        if hash_field != "--hash=sha256:" + item["sha256"]:
            raise ValueError("fixture runtime lock differs from frozen wheel")
        rows.append(
            copy(
                store / "inputs/gateway-inputs/dev04/wheels" / item["filename"],
                run / "build/service/wheels" / item["filename"],
                item["sha256"],
            )
        )
    _, wheel, javascript = build_clients(root, run / ".current-clients")
    for source, target in ((wheel, "python"), (javascript, "js")):
        rows.append(copy(source, run / "build" / target / source.name))
    # Preserve package-qualified fixture imports in the service context.
    sources = [root / "tests/__init__.py", root / "tests/support.py"]
    for directory in ("development_slice", "tool_cycle"):
        sources.extend(
            path
            for path in (root / "tests" / directory).iterdir()
            if path.suffix in {".py", ".json"} and path.is_file()
        )
    for source in sorted(sources):
        rows.append(copy(source, run / "build/service" / source.relative_to(root)))
    return rows
