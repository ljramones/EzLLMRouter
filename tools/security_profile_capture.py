"""Inspect immutable images for a narrowly reviewed runtime-profile decision."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess
import tarfile
import tempfile
import threading

from deploy.local.local_profile import DOCKER
from tools.security_elf import application_closure, inspect
from tools.security_resolutions import canonical


def elf_objects(image: str) -> dict:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise ValueError("immutable image required for native inspection")
    owner = "ezllmrouter-qualification-native-review-" + secrets.token_hex(6)
    container = subprocess.check_output(
        [
            *DOCKER,
            "create",
            "--name",
            owner,
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            image,
        ],
        text=True,
        timeout=60,
    ).strip()
    if not re.fullmatch(r"[0-9a-f]{64}", container):
        raise ValueError("invalid owned inspection container")
    objects = {}
    try:
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(
                [*DOCKER, "export", container], stdout=subprocess.PIPE, stderr=errors
            )
            timer = threading.Timer(180, process.kill)
            timer.start()
            try:
                with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
                    for member in archive:
                        if not member.isfile():
                            continue
                        if not 0 <= member.size <= 512 * 1024 * 1024:
                            raise ValueError("oversized native inspection member")
                        source = archive.extractfile(member)
                        prefix = source.read(4)
                        if prefix != b"\x7fELF":
                            continue
                        raw = prefix + source.read()
                        path = "/" + member.name.removeprefix("./")
                        if ".." in Path(path).parts or path in objects:
                            raise ValueError("ambiguous native inspection path")
                        objects[path] = dict(inspect(raw), sha256=hashlib.sha256(raw).hexdigest())
                if process.wait(timeout=10) != 0:
                    raise ValueError("native filesystem export failed")
            finally:
                timer.cancel()
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
    finally:
        subprocess.run([*DOCKER, "rm", container], check=True, capture_output=True, timeout=60)
    return objects


def capture(image: dict, probe: Path, policy: dict, role: str) -> dict:
    if (
        probe.is_symlink()
        or not probe.is_file()
        or hashlib.sha256(probe.read_bytes()).hexdigest() != policy["probe_sha256"]
    ):
        raise ValueError("unreviewed native diagnostic")
    identity = image["image"]["id"]
    objects = elf_objects(identity)
    closure = application_closure(objects)
    configuration = json.loads(
        subprocess.check_output([*DOCKER, "image", "inspect", identity], text=True, timeout=30)
    )[0]
    user = configuration["Config"]["User"]
    if role == "runtime_python":
        user = "10001:10001"  # The qualified ingress/netns roles explicitly override the builder default.
    elif user not in {"10001:10001", "node", "1000:1000"}:
        raise ValueError("profile image defaults to an unreviewed runtime user")
    raw = subprocess.check_output(
        [
            *DOCKER,
            "run",
            "--rm",
            "--network=none",
            "--read-only",
            "--user=" + user,
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--pids-limit=64",
            "--memory=128m",
            "--cpus=1",
            "--mount",
            "type=bind,source=" + str(probe.resolve()) + ",target=/probe,readonly",
            identity,
            "/probe",
        ],
        text=True,
        timeout=30,
    )
    runtime = json.loads(raw)
    return {
        "image": identity,
        "elf_count": len(objects),
        "elf_sha256": canonical(objects),
        "closure_sha256": canonical(closure),
        "closure": closure,
        "unordered_load_objects": sorted(
            path
            for path, row in objects.items()
            if row["type"] in {2, 3} and not row["loads_ordered"]
        ),
        "runtime": runtime,
    }
