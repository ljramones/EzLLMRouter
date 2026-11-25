"""Bind allocator mitigation checks to exact image controls and a reviewed probe."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess

from deploy.local.local_profile import DOCKER

TUNABLES = "glibc.pthread.stack_cache_size=0:glibc.malloc.arena_max=1"
PROBE_SOURCE = "tools/glibc_allocator_probe.c"
SAMPLE = {
    "kind": "sample",
    "glibc": "2.41",
    "arenas": 1,
    "threads": 8,
    "stack_bytes": 524288,
    "stacks_retained": 0,
    "thread_allocations_in_brk_heap": 8,
    "integrity": True,
}
FALLBACK = {
    "kind": "fallback",
    "brk_extension_blocked": True,
    "direct_mmap_disabled": True,
    "fallback_allocation_survives": True,
    "arenas": 1,
}
FAILURE = {"kind": "failure", "enomem": True, "small_allocation_survives": True}


def environment(configuration: dict) -> dict:
    values = []
    for entry in configuration.get("Env", []):
        key, separator, value = entry.partition("=")
        if key == "GLIBC_TUNABLES":
            if not separator:
                raise ValueError("missing allocator control value")
            values.append(value)
        if key in {"LD_PRELOAD", "LD_AUDIT"} and value:
            raise ValueError("unreviewed dynamic loader override")
    if values != [TUNABLES]:
        raise ValueError("allocator controls differ from qualified policy")
    return {"GLIBC_TUNABLES": TUNABLES}


def validate_probe(path: Path | None, expected: str) -> Path:
    if (
        path is None
        or path.is_symlink()
        or not path.is_file()
        or not re.fullmatch("[0-9a-f]{64}", expected)
        or hashlib.sha256(path.read_bytes()).hexdigest() != expected
    ):
        raise ValueError("unreviewed allocator diagnostic")
    return path.resolve()


def select_fields(raw: dict, expected: dict) -> dict:
    if any(
        type(raw.get(key)) is not type(value) or raw[key] != value
        for key, value in expected.items()
    ):
        raise ValueError("allocator diagnostic failed its bounded control")
    return {key: raw[key] for key in expected}


def valid(proof: dict) -> bool:
    try:
        return (
            proof["environment"] == {"GLIBC_TUNABLES": TUNABLES}
            and select_fields(proof["sample"], SAMPLE) == SAMPLE
            and select_fields(proof["fallback"], FALLBACK) == FALLBACK
            and select_fields(proof["failure"], FAILURE) == FAILURE
            and bool(re.fullmatch("[0-9a-f]{64}", proof["probe_sha256"]))
        )
    except (KeyError, TypeError, ValueError):
        return False


def capture(identity: str, configuration: dict, user: str, probe: Path, expected: str) -> dict:
    executable = validate_probe(probe, expected)
    controls = environment(configuration)
    if not re.fullmatch("sha256:[0-9a-f]{64}", identity) or user not in {
        "10001:10001",
        "node",
        "1000:1000",
    }:
        raise ValueError("allocator inspection requires an immutable image and non-root user")
    prefix = [
        *DOCKER,
        "run",
        "--rm",
        "--pull=never",
        "--network=none",
        "--read-only",
        "--user=" + user,
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--pids-limit=128",
        "--memory=256m",
        "--cpus=1",
        "--mount",
        "type=bind,source=" + str(executable) + ",target=/probe,readonly",
        "--entrypoint=/probe",
        identity,
    ]
    result = {"environment": controls, "probe_sha256": expected}
    for mode, fields in (("sample", SAMPLE), ("fallback", FALLBACK), ("failure", FAILURE)):
        raw = subprocess.check_output([*prefix, "--" + mode], text=True, timeout=30)
        result[mode] = select_fields(json.loads(raw), fields)
    return result
