"""Cold copies of disposable qualification volumes; never a live-profile backup."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
import subprocess
import tarfile

from deploy.local import local_profile as profile

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


def archive_members(path: Path) -> int:
    """Accept only regular files/directories from the two known container owners."""
    names = set()
    with tarfile.open(path, "r:") as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            if (
                name.is_absolute()
                or ".." in name.parts
                or str(name) in names
                or not (member.isfile() or member.isdir())
                or member.uid not in (0, 10001)
                or member.gid not in (0, 10001)
                or member.mode & 0o7022
            ):
                raise ValueError("unsafe disposable volume archive")
            names.add(str(name))
    if not names:
        raise ValueError("empty disposable volume archive")
    return len(names)


def helper(volume: str, *, readonly: bool) -> list[str]:
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
        "--mount",
        "type=volume,src=" + volume + ",dst=/volume" + (",readonly" if readonly else ""),
        profile.BASE,
    ]


def cold_copy(source: str, target: str, directory: Path, env: dict[str, str]) -> list[dict]:
    """Caller has stopped source and created empty, separate target volumes."""
    if source == target:
        raise ValueError("restore must use separate project volumes")
    results = []
    for kind in DURABLE:
        original = owned_volume(source, kind, env)
        restored = owned_volume(target, kind, env)
        path = directory / (kind + ".tar")
        # Binary archive bytes and credentials never pass through command logs.
        with path.open("xb") as stream:
            path.chmod(0o600)
            subprocess.run(
                [*helper(original, readonly=True), "tar", "-cpf", "-", "-C", "/volume", "."],
                stdout=stream,
                stderr=subprocess.PIPE,
                check=True,
                timeout=120,
                env=env,
            )
        count = archive_members(path)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        # Refuse to overwrite any destination, including files hidden by ls.
        profile.command(
            "empty-restore-" + kind,
            [
                *helper(restored, readonly=True),
                "python",
                "-I",
                "-S",
                "-c",
                "from pathlib import Path; assert not any(Path('/volume').iterdir())",
            ],
            env,
        )
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                raise ValueError("backup changed before restore")
            stream.seek(0)
            subprocess.run(
                [
                    *helper(restored, readonly=False),
                    "tar",
                    "-xpf",
                    "-",
                    "--numeric-owner",
                    "-C",
                    "/volume",
                ],
                stdin=stream,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
                timeout=120,
                env=env,
            )
        results.append(
            {"volume": kind, "sha256": digest, "members": count, "bytes": path.stat().st_size}
        )
    return results
