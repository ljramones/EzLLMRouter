"""prepare resolution domain; entry points remain on the facade."""

from __future__ import annotations

import argparse as argparse
import ast as ast
import base64 as base64
import csv as csv
import hashlib as hashlib
import io as io
import json as json
import os as os
from pathlib import Path as Path
import re as re
import shutil as shutil
import signal as signal
import stat as stat
import subprocess as subprocess
import sys as sys
import tarfile as tarfile
import time as time
import unicodedata as unicodedata
import uuid as uuid
import zipfile as zipfile


def static_requirements():
    from tools.gateway.docker import prepare as _api

    if _api.SOURCE.is_symlink() or _api.sha(_api.SOURCE) != _api.SOURCE_SHA:
        raise ValueError("selected source mismatch")
    with _api.tarfile.open(_api.SOURCE, "r:gz") as archive:
        matches = [m for m in archive.getmembers() if m.name == "litellm-1.105.1/PKG-INFO"]
        if len(matches) != 1 or not matches[0].isreg():
            raise ValueError("regular PKG-INFO member missing")
        raw = archive.extractfile(matches[0]).read()
    if _api.hashlib.sha256(raw).hexdigest() != _api.PKG_INFO_SHA:
        raise ValueError("PKG-INFO mismatch")
    selected = []
    for line in raw.decode().splitlines():
        if not line.startswith("Requires-Dist: "):
            continue
        value = line[len("Requires-Dist: ") :]
        if " ; " not in value:
            selected.append(value)
            continue
        name, marker = value.split(" ; ", 1)
        if "extra == 'proxy'" in marker:
            marker = (
                marker.replace(" and extra == 'proxy'", "").replace("extra == 'proxy'", "").strip()
            )
            if "extra" in marker:
                raise ValueError("unhandled extra marker")
            selected.append(name + (" ; " + marker if marker else ""))
        elif "extra" not in marker:
            selected.append(value)
    if (
        len(selected) != 54
        or "litellm-enterprise==0.1.73" not in selected
        or "litellm-proxy-extras==0.4.105" not in selected
    ):
        raise ValueError("selected proxy root changed")
    return selected


def uv_argv(run, requirement_path):
    from tools.gateway.docker import prepare as _api

    return [
        str(_api.UV),
        "--no-config",
        "--no-python-downloads",
        "pip",
        "compile",
        str(requirement_path),
        "--no-build",
        "--no-sources",
        "--no-header",
        "--no-annotate",
        "--python-version",
        ".".join(map(str, _api.TARGET_PYTHON)),
        "--python-platform",
        "aarch64-manylinux_2_36",
        "--generate-hashes",
        "--keyring-provider",
        "disabled",
        "--default-index",
        "https://pypi.org/simple",
        "--cache-dir",
        str(run / "uv-cache"),
        "--exclude-newer",
        "2026-10-17T23:59:59Z",
        "--output-file",
        str(run / "candidate-runtime.lock"),
    ]


def validate_marker(marker):
    """Accept only inert PEP 508-style comparisons; never evaluate a marker."""
    from tools.gateway.docker import prepare as _api

    names = {
        "implementation_name",
        "implementation_version",
        "os_name",
        "platform_machine",
        "platform_python_implementation",
        "platform_release",
        "platform_system",
        "platform_version",
        "python_full_version",
        "python_version",
        "sys_platform",
        "extra",
        "extras",
        "dependency_groups",
    }
    try:
        tree = _api.ast.parse(marker, mode="eval")
    except SyntaxError as caught_error:
        raise ValueError("malformed resolver marker") from caught_error

    def operand(node):
        return (isinstance(node, _api.ast.Name) and node.id in names) or (
            isinstance(node, _api.ast.Constant) and isinstance(node.value, str)
        )

    def expression(node):
        if isinstance(node, _api.ast.BoolOp) and isinstance(node.op, (_api.ast.And, _api.ast.Or)):
            return len(node.values) >= 2 and all(expression(value) for value in node.values)
        if isinstance(node, _api.ast.Compare):
            return (
                operand(node.left)
                and all(operand(x) for x in node.comparators)
                and all(
                    isinstance(
                        op,
                        (
                            _api.ast.Eq,
                            _api.ast.NotEq,
                            _api.ast.Lt,
                            _api.ast.LtE,
                            _api.ast.Gt,
                            _api.ast.GtE,
                            _api.ast.In,
                            _api.ast.NotIn,
                        ),
                    )
                    for op in node.ops
                )
            )
        return False

    if not expression(tree.body):
        raise ValueError("unsupported resolver marker")


def parse_resolver_lock(raw):
    """Validate uv's hashed requirements as data; comments never grant a pin."""
    from tools.gateway.docker import prepare as _api

    text = raw.decode("utf-8")
    if "\x00" in text:
        raise ValueError("NUL in resolver output")
    pins = {}
    current = None
    for number, line in enumerate(text.splitlines(), 1):
        active = line.strip()
        if not active or active.startswith("#"):
            continue
        active = _api.re.split(r"\s+#", active, maxsplit=1)[0].rstrip()
        if active.endswith("\\"):
            active = active[:-1].rstrip()
        if active.startswith("--hash=sha256:"):
            digest = active[len("--hash=sha256:") :]
            if current is None or not _api.SHA_RE.fullmatch(digest):
                raise ValueError("orphan or invalid hash at line " + str(number))
            pins[current]["hashes"].add(digest)
            continue
        match = _api.re.fullmatch(
            r"([A-Za-z0-9][A-Za-z0-9._-]*)==([0-9][A-Za-z0-9.!+_-]*)(?:\s*;\s*(.+))?", active
        )
        if not match:
            raise ValueError("unsupported active resolver line " + str(number))
        name, version, marker = match.groups()
        if marker is not None:
            if (
                not _api.re.fullmatch(r"""[A-Za-z0-9_ .'"<>=!()+-]+""", marker)
                or "://" in marker
                or "@" in marker
            ):
                raise ValueError("unsupported marker at line " + str(number))
            _api.validate_marker(marker)
        normalized = _api.re.sub(r"[-_.]+", "-", name).lower()
        if normalized in pins:
            raise ValueError("duplicate normalized resolver package: " + normalized)
        if current is not None and not pins[current]["hashes"]:
            raise ValueError("unhashed resolver pin: " + current)
        pins[normalized] = {"version": version, "marker": marker, "hashes": set()}
        current = normalized
    if not pins or any(not item["hashes"] for item in pins.values()):
        raise ValueError("resolver output has missing hashed exact pins")
    return pins


def execute_uv(argv, run, env):
    from tools.gateway.docker import prepare as _api

    process = _api.subprocess.Popen(
        argv,
        cwd=run,
        env=env,
        stdout=_api.subprocess.PIPE,
        stderr=_api.subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    started = _api.time.monotonic()
    reason = None
    while True:
        try:
            stdout, stderr = process.communicate(timeout=0.2)
            break
        except _api.subprocess.TimeoutExpired:
            if _api.time.monotonic() - started > _api.RESOLVE_SECONDS:
                reason = "TOTAL_RESOLUTION_TIMEOUT"
            else:
                try:
                    if _api.run_bytes(run) > _api.MAX_AGGREGATE:
                        reason = "AGGREGATE_BYTE_LIMIT"
                except ValueError as exc:
                    reason = "UNSAFE_RUN_CONTENT: " + str(exc)
            if reason:
                try:
                    _api.os.killpg(process.pid, _api.signal.SIGKILL)
                except ProcessLookupError:
                    pass
                stdout, stderr = process.communicate()
                break
    try:
        if _api.run_bytes(run) > _api.MAX_AGGREGATE:
            reason = reason or "AGGREGATE_BYTE_LIMIT"
    except ValueError as exc:
        reason = reason or "UNSAFE_RUN_CONTENT: " + str(exc)
    return {
        "exit_status": process.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "stop_reason": reason,
        "elapsed_seconds": round(_api.time.monotonic() - started, 3),
    }


def resolve_online(run, runner=None):
    from tools.gateway.docker import prepare as _api

    if _api.UV.is_symlink() and _api.sha(_api.UV) != _api.UV_SHA:
        raise ValueError("uv tool receipt changed")
    if _api.sha(_api.UV) != _api.UV_SHA:
        raise ValueError("uv tool receipt changed")
    roots = _api.static_requirements()
    requirement_path = run / "proxy-runtime.in"
    _api.write_new(requirement_path, ("\n".join(roots) + "\n").encode())
    _api.child_dir(run, "uv-cache")
    _api.child_dir(run, "home")
    _api.child_dir(run, "tmp")
    argv = _api.uv_argv(run, requirement_path)
    env = {
        "PATH": "/usr/bin:/bin:/opt/homebrew/bin",
        "HOME": str(run / "home"),
        "TMPDIR": str(run / "tmp"),
        "UV_NO_PROGRESS": "1",
        "UV_PYTHON_DOWNLOADS": "never",
        "UV_HTTP_TIMEOUT": "10",
        "UV_HTTP_RETRIES": "0",
        "UV_KEYRING_PROVIDER": "disabled",
    }
    record = {
        "argv": argv,
        "cwd": str(run),
        "environment": env,
        "input_sha256": _api.sha(requirement_path),
        "input_count": len(roots),
    }
    try:
        result = (runner or _api.execute_uv)(argv, run, env)
    except Exception as exc:
        record.update(
            {
                "status": "PROCESS_INVOCATION_FAILED",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
        _api.receipt(run, "resolve", record)
        return record
    if isinstance(result, dict):
        record.update(result)
    output = run / "candidate-runtime.lock"
    try:
        if not isinstance(result, dict) or type(result.get("exit_status")) is not int:
            raise ValueError("resolver process result lacks integer exit status")
        if output.exists() or output.is_symlink():
            _api.safe_component_path(output, run, require_file=True)
            if output.stat().st_size > _api.MAX_TRANSFER:
                raise ValueError("resolver output exceeds 50 MB data bound")
            record.update(
                {"output_sha256": _api.sha(output), "output_bytes": output.stat().st_size}
            )
        if result["exit_status"] == 0 and not result.get("stop_reason"):
            if _api.run_bytes(run) > _api.MAX_AGGREGATE:
                raise ValueError("resolver aggregate byte limit exceeded")
            _api.safe_component_path(output, run, require_file=True)
            pins = _api.parse_resolver_lock(output.read_bytes())
            record.update(
                {
                    "status": "METADATA_RESOLUTION_PROPOSAL_ONLY",
                    "pins": len(pins),
                    "hashed_exact_pins": len(pins),
                }
            )
        else:
            record["status"] = "UNRESOLVED_NO_BACKEND_EXECUTED"
    except Exception as exc:
        record.update(
            {
                "status": "OUTPUT_VALIDATION_FAILED",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
    _api.receipt(run, "resolve", record)
    return record
