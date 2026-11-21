"""Offline, redacted secret detection over source files and reachable Git blobs."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAX_BLOB = 16 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
PATTERNS = {
    "provider": re.compile(rb"(?<![A-Za-z0-9])sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}"),
    "aws": re.compile(rb"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])"),
    "github": re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"),
    "private_key": re.compile(
        rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----"
    ),
    "entropy": re.compile(rb"(?<![A-Za-z0-9+/_=-])[A-Za-z0-9+/_=-]{40,}(?![A-Za-z0-9+/_=-])"),
}


def detect(data: bytes) -> list[dict[str, Any]]:
    found = []
    for rule, pattern in PATTERNS.items():
        for match in pattern.finditer(data):
            value = match[0]
            if rule == "entropy":
                hexadecimal = bool(re.fullmatch(rb"[0-9a-fA-F]+", value))
                if hexadecimal and not re.search(
                    rb"(?i)(?:api[_-]?key|password|secret|access[_-]?token|auth[_-]?token|client[_-]?secret|master[_-]?key|encryption[_-]?key)[\"']?\s*[:=]\s*[\"']?$",
                    data[max(0, match.start() - 100) : match.start()],
                ):
                    continue
                if not hexadecimal and not all(
                    any(start <= char <= end for char in value)
                    for start, end in ((65, 90), (97, 122), (48, 57))
                ):
                    continue
                entropy = -sum(
                    (count / len(value)) * math.log2(count / len(value))
                    for count in Counter(value).values()
                )
                if entropy < (3.2 if hexadecimal else 4.7):
                    continue
            found.append(
                {
                    "rule": rule,
                    "line": data.count(b"\n", 0, match.start()) + 1,
                    "fingerprint": hashlib.sha256(rule.encode() + b"\0" + value).hexdigest(),
                }
            )
    return sorted(found, key=lambda row: (row["line"], row["rule"], row["fingerprint"]))


def git(root: Path, *arguments: str, data: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", "-C", str(root), "-c", "protocol.allow=never", *arguments],
        input=data,
        capture_output=True,
        check=True,
        timeout=120,
    ).stdout


def scan(root: Path = ROOT, *, include_history: bool = True) -> dict[str, Any]:
    root = root.resolve()
    if include_history and git(root, "rev-parse", "--is-shallow-repository").strip() != b"false":
        raise ValueError("full-history secret scan requires a nonshallow repository")
    findings: list[dict[str, Any]] = []
    objects = 0
    total = 0
    cache: dict[str, list[dict[str, Any]]] = {}

    def inspect(source: str, raw: bytes) -> None:
        nonlocal objects, total
        if len(raw) > MAX_BLOB:
            raise ValueError("secret scan blob exceeds explicit size limit")
        total += len(raw)
        if total > MAX_TOTAL:
            raise ValueError("secret scan exceeds explicit total-byte limit")
        sha = hashlib.sha256(raw).hexdigest()
        if sha not in cache:
            cache[sha] = detect(raw)
        objects += 1
        findings.extend(
            {"source": source, "blob_sha256": sha, "identity": identity} for identity in cache[sha]
        )

    names = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0")
    for encoded in sorted(set(names)):
        if not encoded:
            continue
        name = encoded.decode("utf-8")
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("secret scan source escapes the checkout or is a symlink")
        if not path.exists():
            continue  # Tracked deletions still appear in history.
        if not path.is_file():
            raise ValueError("secret scan source must be a regular file")
        inspect("tree:" + name, path.read_bytes())
    if include_history:
        identifiers = git(root, "rev-list", "--objects", "--all", "--no-object-names").splitlines()
        if identifiers:
            headers = git(root, "cat-file", "--batch-check", data=b"\n".join(identifiers) + b"\n")
            blobs = []
            size = 0
            for line in headers.splitlines():
                fields = line.split()
                if len(fields) != 3:
                    raise ValueError("unreadable Git object")
                if fields[1] != b"blob":
                    continue
                length = int(fields[2])
                size += length
                if length > MAX_BLOB or size + total > MAX_TOTAL:
                    raise ValueError("Git history exceeds secret scan size limits")
                blobs.append(fields[0])
            data = (
                git(root, "cat-file", "--batch", data=b"\n".join(blobs) + b"\n") if blobs else b""
            )
            offset = 0
            for identifier in blobs:
                end = data.index(b"\n", offset)
                fields = data[offset:end].split()
                if len(fields) != 3 or fields[0] != identifier or fields[1] != b"blob":
                    raise ValueError("Git blob identity mismatch")
                size = int(fields[2])
                offset = end + 1
                raw = data[offset : offset + size]
                offset += size
                if len(raw) != size or data[offset : offset + 1] != b"\n":
                    raise ValueError("truncated Git blob")
                offset += 1
                inspect("history:" + identifier.decode(), raw)
            if offset != len(data):
                raise ValueError("unexpected Git object output")
    return {
        "format": "ezllmrouter-secret-scan-v1",
        "scope": "working tree and all reachable Git blobs"
        if include_history
        else "working tree only",
        "objects": objects,
        "bytes": total,
        "findings": findings,
        "scanner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }


def policy_errors(report: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    observed: dict[str, set[str]] = {}
    for row in report["findings"]:
        observed.setdefault(row["blob_sha256"], set()).add(
            json.dumps(row["identity"], sort_keys=True)
        )
    allowed = {}
    errors = []
    for row in policy["exceptions"]:
        sha = row["blob_sha256"]
        identities = {json.dumps(identity, sort_keys=True) for identity in row["findings"]}
        if (
            not re.fullmatch("[0-9a-f]{64}", sha)
            or sha in allowed
            or not row["reason"].strip()
            or not identities
            or len(identities) != len(row["findings"])
        ):
            errors.append("invalid/duplicate secret fixture exception")
            continue
        allowed[sha] = identities
        if observed.get(sha) != identities:
            errors.append("changed/stale secret fixture exception: " + sha)
    for sha, identities in observed.items():
        if identities != allowed.get(sha):
            errors.append("unreviewed secret-like source: " + sha)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".artifacts/security/secrets.json")
    args = parser.parse_args()
    report: dict[str, Any] = {"passed": False}
    try:
        report.update(scan())
        policy = json.loads((ROOT / "tools/security_secrets_exceptions.json").read_text())
        report["errors"] = policy_errors(report, policy)
        report["passed"] = not report["errors"]
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        report["error_type"] = type(error).__name__
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        "Secret scan "
        + ("passed" if report["passed"] else "failed")
        + "; redacted evidence: "
        + str(args.output)
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
