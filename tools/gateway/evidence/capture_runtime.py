"""Redacted runtime export with an explicit credential-generation lifecycle."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile


SECRET_NAMES = ("token", "provider-key")
REDACTION = b"[REDACTED-SYNTHETIC-CREDENTIAL]"


class CaptureLimit(RuntimeError):
    pass


def credentials(run):
    attempted = (run / "generate-credentials.argv").exists()
    state_file = run / "credential-generation-state.json"
    if attempted and not state_file.is_file():
        raise CaptureLimit("credential generation began without a readable lifecycle record")
    if state_file.exists() and not attempted:
        raise CaptureLimit("credential lifecycle exists without a generation command record")
    state = json.loads(state_file.read_text()) if attempted else {"expected": []}
    expected = state["expected"]
    if type(expected) is not list or any(name not in SECRET_NAMES for name in expected):
        raise CaptureLimit("invalid credential lifecycle record")
    if (run / "generate-credentials.exit").is_file():
        exit_code = int((run / "generate-credentials.exit").read_text().strip())
        if exit_code == 0 and set(expected) != set(SECRET_NAMES):
            raise CaptureLimit("successful generation has incomplete credential lifecycle")
    values = []
    for name in SECRET_NAMES:
        path = run / name
        if path.is_symlink():
            raise CaptureLimit("credential path is a symlink: " + name)
        if not path.exists():
            if name in expected:
                raise CaptureLimit("expected credential is missing: " + name)
            continue
        try:
            value = path.read_bytes().strip()
        except OSError as exc:
            raise CaptureLimit("expected credential is unreadable: " + name) from exc
        if not value:
            raise CaptureLimit("credential is empty: " + name)
        values.append(value)
    return values


def capture(run, out, prefix):
    target = out / f"{prefix}-RUNTIME-{run.name}.zip"
    if target.exists() or target.is_symlink():
        raise CaptureLimit("runtime packet collision")
    secrets = credentials(run)
    files = []
    for path in sorted(run.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(run)
        if ("build" in relative.parts or path.name.endswith((".keys.json", ".keys.json.lock", ".sealed")) or path.name in
                {*SECRET_NAMES, "capture.stdout", "capture.stderr"}):
            continue
        raw = path.read_bytes()
        redacted = False
        for secret in secrets:
            if secret in raw:
                raw = raw.replace(secret, REDACTION)
                redacted = True
        files.append((relative.as_posix(), raw, redacted))
    rows = []
    with zipfile.ZipFile(target, "x", zipfile.ZIP_DEFLATED) as archive:
        for name, raw, redacted in files:
            archive.writestr(name, raw)
            rows.append({"path": name, "bytes": len(raw),
                         "sha256": hashlib.sha256(raw).hexdigest(),
                         "credential_redacted": redacted})
        archive.writestr("EVIDENCE-MANIFEST.json",
                         json.dumps({"files": rows, "self_excluded": True}, indent=2))
    return {"runtime_packet": str(target),
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "payloads": len(rows)}


def main():
    try:
        print(json.dumps(capture(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])))
    except (CaptureLimit, OSError, ValueError, KeyError) as exc:
        print("runtime capture withheld: " + str(exc), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
