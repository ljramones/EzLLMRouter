"""Check the reviewed CI bootstrap pins without contacting package registries."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from tools.ci_toolchains import load_policy


def errors(root: Path) -> list[str]:
    policy: dict[str, Any] = json.loads((root / ".github/bootstrap-inputs.json").read_text())
    failures = []
    try:
        load_policy(root)
    except (KeyError, TypeError, ValueError) as error:
        failures.append("invalid CI toolchain policy: " + str(error))
    uv = policy["uv"]
    artifacts = [uv, *uv.get("platform_artifacts", [])]
    expected = f"uv=={uv['version']} " + " ".join(
        "--hash=sha256:" + artifact["sha256"] for artifact in artifacts
    )
    lock = (root / ".github/requirements-bootstrap.lock").read_text()
    records = [
        line for line in lock.splitlines() if line.strip() and not line.lstrip().startswith("#")
    ]
    if records != [expected]:
        failures.append("bootstrap lock differs from reviewed wheel identity")
    if len({artifact["filename"] for artifact in artifacts}) != len(artifacts):
        failures.append("duplicate bootstrap artifact")
    if any(
        not re.fullmatch("[0-9a-f]{64}", artifact["sha256"])
        or artifact["startup_hooks"] != []
        or artifact["yanked"] is not False
        or not artifact["filename"].startswith(f"uv-{uv['version']}-py3-none-")
        or not artifact["url"].startswith("https://files.pythonhosted.org/packages/")
        or not artifact["url"].endswith("/" + artifact["filename"])
        for artifact in artifacts
    ):
        failures.append("invalid/unreviewed bootstrap artifact")
    for path in sorted(
        {
            path
            for pattern in ("*.yml", "*.yaml")
            for path in (root / ".github/workflows").glob(pattern)
        }
    ):
        for line in path.read_text().splitlines():
            if line.lstrip().startswith("#"):
                continue
            match = re.search(r"uses:\s*([^\s@]+)@([^\s#]+)", line)
            if match and not re.fullmatch("[0-9a-f]{40}", match[2]):
                failures.append("mutable action reference: " + path.name)
            if match and match[1] in {"actions/setup-java", "actions/setup-dotnet"}:
                failures.append("toolchain installation bypasses reviewed archive: " + path.name)
            if (
                match
                and match[1] == "actions/setup-dotnet"
                and match[2] != policy["setup_dotnet"]["commit"]
            ):
                failures.append("unreviewed setup-dotnet commit: " + path.name)
            if "pip install" in line:
                if not all(
                    part in line
                    for part in (
                        "--force-reinstall",
                        "--only-binary=:all:",
                        "--no-deps",
                        "--require-hashes",
                        "-r .github/requirements-bootstrap.lock",
                    )
                ):
                    failures.append("unhashed bootstrap installation: " + path.name)
            if re.search(r"npm\s+install\s+--global.*typescript", line):
                failures.append("TypeScript installation bypasses lock integrity: " + path.name)
    return failures + workflow_toolchain_errors(root)


def workflow_toolchain_errors(root: Path) -> list[str]:
    source = (root / ".github/workflows/check.yml").read_text()
    failures = []
    for job, tools in (
        ("native-clients", ("java",)),
        ("dotnet-client", ("dotnet",)),
        ("platform-clients", ("java", "dotnet")),
    ):
        match = re.search(r"(?ms)^  " + job + r":\n(.*?)(?=^  [\w-]+:|\Z)", source)
        block = match[1] if match else ""
        for tool in tools:
            if not re.search(r"(?m)^\s+run: .* -I -S tools/ci_toolchains\.py " + tool + "$", block):
                failures.append("missing hash-verified toolchain: " + job + "/" + tool)
    match = re.search(r"(?ms)^  typescript-client:\n(.*?)(?=^  [\w-]+:|\Z)", source)
    block = match[1] if match else ""
    if not all(
        value in block
        for value in (
            "run: npm --prefix tests/playwright ci --ignore-scripts --no-audit --no-fund",
            "TSC_BINARY: ${{ github.workspace }}/tests/playwright/node_modules/.bin/tsc",
        )
    ):
        failures.append("TypeScript job must install and use the integrity-locked compiler")
    return failures
