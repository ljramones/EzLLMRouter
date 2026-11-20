"""Bounded command capture and private evidence files for local workflows."""

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
import re
import subprocess
import sys
import time


def _text(value: str | bytes | None) -> str:
    return value.decode(errors="replace") if isinstance(value, bytes) else value or ""


def capture(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    payload: str | None = None,
    timeout: float = 180,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(argv, 124, _text(exc.stdout), _text(exc.stderr))


def record(
    directory: Path,
    name: str,
    result: subprocess.CompletedProcess[str],
    redact: Callable[[str], str],
    *,
    suffix: str = ".txt",
) -> subprocess.CompletedProcess[str]:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}", name) is None:
        raise ValueError("invalid command record name")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    safe = subprocess.CompletedProcess(
        result.args, result.returncode, redact(result.stdout), redact(result.stderr)
    )
    for extension, content in (
        ("stdout", safe.stdout),
        ("stderr", safe.stderr),
        ("exit", str(safe.returncode) + "\n"),
    ):
        path = directory / (name + "." + extension + suffix)
        if path.is_symlink():
            raise ValueError("command record must not be a symlink")
        path.write_text(content)
        path.chmod(0o600)
    return safe


def target_command(
    name: str,
    argv: Sequence[str],
    directory: Path,
    *,
    cwd: Path,
    env: Mapping[str, str],
    redact: Callable[[str], str],
    label: str,
    records: Path,
    timeout: float = 180,
    allowed: Sequence[int] = (0,),
) -> tuple[str, int]:
    started = time.time()
    result = record(directory, name, capture(argv, cwd=cwd, env=env, timeout=timeout), redact)
    if name == "build-images":
        for stage in ("build-receiver", "build-worker", "build-service"):
            for extension in ("stdout", "stderr", "exit"):
                source = records / (stage + "." + extension)
                if source.is_file() and source.stat().st_mtime >= started - 1:
                    target = directory / (stage + "." + extension + ".txt")
                    target.write_text(redact(source.read_text()))
                    target.chmod(0o600)
    print(f"{label}: {name} exited {result.returncode}", flush=True)
    if result.returncode not in allowed:
        print("\n".join(result.stderr.splitlines()[-12:])[:1500], file=sys.stderr)
        raise RuntimeError(name + " failed; inspect separately saved redacted output")
    return result.stdout.strip(), result.returncode
