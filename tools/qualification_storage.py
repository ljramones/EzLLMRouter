"""Cold copies of disposable qualification volumes; never a live-profile backup."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess

from deploy.local import local_profile as profile
from tools.volume_archive import archive_members as archive_members

DURABLE = ("service_data", "credential_data", "receiver_data")


def owned_volume(project: str, kind: str, env: dict[str, str]) -> str:
    if not project.startswith("ezllmrouter-qualification-") or kind not in DURABLE:
        raise ValueError("qualification volume namespace required")
    name = project + "_" + kind
    output, _ = profile.command(
        "inspect-" + name, [*profile.DOCKER, "volume", "inspect", name], env
    )
    import json

    rows = json.loads(output)
    if (
        len(rows) != 1
        or rows[0].get("Name") != name
        or rows[0].get("Labels", {}).get("com.docker.compose.project") != project
        or rows[0].get("Labels", {}).get("com.docker.compose.volume") != kind
    ):
        raise ValueError("volume ownership mismatch")
    running, _ = profile.command(
        "volume-users-" + name, [*profile.DOCKER, "ps", "-q", "--filter", "volume=" + name], env
    )
    if running:
        raise ValueError("cold copy requires stopped volume users")
    return name


def helper(volume: str, image: str, *, readonly: bool) -> list[str]:
    return [
        *profile.DOCKER,
        "run",
        "--rm",
        "-i",
        "--network=none",
        "--read-only",
        "--user=0:0",
        "--cap-drop=ALL",
        "--cap-add=CHOWN",
        "--cap-add=DAC_OVERRIDE",
        "--cap-add=FOWNER",
        "--security-opt=no-new-privileges:true",
        "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=144m,mode=0700",
        "--mount",
        "type=bind,src="
        + str(profile.ROOT / "tools/volume_archive.py")
        + ",dst=/archive.py,readonly",
        "--mount",
        "type=volume,src=" + volume + ",dst=/volume" + (",readonly" if readonly else ""),
        image,
        "python",
        "-I",
        "-S",
        "/archive.py",
    ]


def cold_copy(source: str, target: str, directory: Path, env: dict[str, str]) -> list[dict]:
    """Caller has stopped source and created empty, separate target volumes."""
    if source == target:
        raise ValueError("restore must use separate project volumes")
    output, _ = profile.command(
        "cold-copy-runtime-image",
        [*profile.DOCKER, "image", "inspect", env["EZLLMROUTER_PYTHON_IMAGE"]],
        env,
    )
    images = json.loads(output)
    if len(images) != 1 or re.fullmatch("sha256:[0-9a-f]{64}", images[0].get("Id", "")) is None:
        raise ValueError("immutable patched runtime image required")
    image = images[0]["Id"]
    results = []
    for kind in DURABLE:
        original = owned_volume(source, kind, env)
        restored = owned_volume(target, kind, env)
        path = directory / (kind + ".tar")
        # Binary archive bytes and credentials never pass through command logs.
        with path.open("xb") as stream:
            path.chmod(0o600)
            subprocess.run(
                [*helper(original, image, readonly=True), "create"],
                stdout=stream,
                stderr=subprocess.PIPE,
                check=True,
                timeout=120,
                env=env,
            )
        count = archive_members(path)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        with path.open("rb") as stream:
            completed = subprocess.run(
                [
                    *helper(restored, image, readonly=False),
                    "restore",
                    "--sha256",
                    digest,
                ],
                stdin=stream,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
                timeout=120,
                env=env,
            )
        receipt = {"sha256": digest, "members": count, "bytes": path.stat().st_size}
        if json.loads(completed.stdout) != receipt:
            raise ValueError("restore receipt differs from validated archive")
        results.append({"volume": kind, **receipt})
    return results
