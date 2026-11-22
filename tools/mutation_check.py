"""Bounded, source-pinned decision mutations in disposable source copies."""

import argparse
from contextlib import suppress
from collections import Counter
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "tests/fixtures/mutations/critical.json"
PREFIXES = ("server/", "clients/python/", "tests/", "tools/", "deploy/", "web/")


def source_files(root):
    raw = subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
    )
    names = sorted(
        {
            value.decode()
            for value in raw.split(b"\0")
            if value and value.decode().startswith(PREFIXES)
        }
    )
    if not names or sum((root / name).stat().st_size for name in names) > 64 * 1024 * 1024:
        raise ValueError("mutation source-copy size budget")
    for name in names:
        source = root / name
        if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(root):
            raise ValueError("mutation source escapes its declared root")
    return names


def invoke(copy, row, directory, phase, timeout):
    report = directory / (phase + ".json")
    temporary = directory / (phase + "-tmp")
    temporary.mkdir()
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            str(copy / path) for path in ("server/src", "clients/python/src")
        ),
        "TMPDIR": str(temporary),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    command = [
        sys.executable,
        "-B",
        "-m",
        "tools.mutation_probe",
        row["selector"],
        row["path"],
        str(report),
    ]
    started = time.monotonic()
    try:
        with (directory / (phase + ".log")).open("w") as log:
            process = subprocess.Popen(
                command,
                cwd=copy,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                return {"outcome": "timeout", "seconds": time.monotonic() - started}
            finally:
                if process.poll() is None:
                    with suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)
    finally:
        shutil.rmtree(temporary)
    if not report.is_file():
        return {
            "outcome": "invalid",
            "reason": "missing child result",
            "returncode": process.returncode,
        }
    result = json.loads(report.read_text())
    result["seconds"] = time.monotonic() - started
    if not result.get("valid") or process.returncode:
        result["outcome"] = "invalid"
    else:
        result["outcome"] = "survived" if result["passed"] else "killed"
    return result


def run(policy, directory, *, root=ROOT, timeout=12):
    if os.name != "posix":
        raise ValueError("mutation process-group cleanup requires POSIX")
    if not 0.05 <= timeout <= 60 or not 1 <= len(policy["mutations"]) <= 32:
        raise ValueError("mutation run budget")
    identities = [row["id"] for row in policy["mutations"]]
    if len(set(identities)) != len(identities) or any(
        not re.fullmatch("[a-z][a-z0-9-]{0,63}", identity) for identity in identities
    ):
        raise ValueError("invalid mutation identity")
    root, directory = root.resolve(), directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    names, results = source_files(root), []
    summary = {
        "format": "ezllmrouter.mutation-run.v1",
        "scope": "Declared source-pinned decisions; independent test processes; synthetic offline inputs",
        "passed": False,
        "mutations": results,
    }
    try:
        for row in policy["mutations"]:
            if row["path"] not in names:
                raise ValueError("mutation path is outside the source inventory")
            raw = (root / row["path"]).read_bytes()
            if (
                row["path"] not in names
                or hashlib.sha256(raw).hexdigest() != row["source_sha256"]
                or raw.count(row["before"].encode()) != 1
            ):
                raise ValueError("mutation source identity changed: " + row["id"])
            entry = {
                "id": row["id"],
                "source_sha256": row["source_sha256"],
                "selector": row["selector"],
                "outcome": "invalid",
            }
            results.append(entry)
            case = directory / row["id"]
            case.mkdir()
            with tempfile.TemporaryDirectory(prefix="source-", dir=case) as temporary:
                copy = Path(temporary)
                for name in names:
                    target = copy / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(root / name, target)
                baseline = invoke(copy, row, case, "baseline", timeout)
                entry["baseline"] = baseline
                if baseline["outcome"] != "survived":
                    entry["outcome"] = "timeout" if baseline["outcome"] == "timeout" else "invalid"
                    entry["reason"] = "baseline did not pass"
                    continue
                changed = raw.replace(row["before"].encode(), row["after"].encode(), 1)
                entry["mutant_sha256"] = hashlib.sha256(changed).hexdigest()
                if changed == raw:
                    raise ValueError("empty mutation")
                try:
                    compile(changed, row["path"], "exec")
                except SyntaxError:
                    entry["reason"] = "mutant syntax invalid"
                    continue
                (copy / row["path"]).write_bytes(changed)
                entry["result"] = invoke(copy, row, case, "mutant", timeout)
                entry["outcome"] = entry["result"]["outcome"]
        summary["passed"] = len(results) == len(policy["mutations"]) and all(
            row["outcome"] == "killed" for row in results
        )
        return summary
    finally:
        summary["counts"] = {
            name: Counter(row["outcome"] for row in results)[name]
            for name in ("killed", "survived", "invalid", "timeout")
        }
        (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=12)
    args = parser.parse_args()
    from .test_network import block_network
    from contextlib import ExitStack

    with ExitStack() as stack:
        block_network(stack)
        report = run(json.loads(POLICY.read_text()), args.output, timeout=args.timeout)
    print(json.dumps({"passed": report["passed"], **report["counts"]}, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
