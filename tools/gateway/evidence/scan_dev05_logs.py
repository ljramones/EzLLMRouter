"""Inspect selected runtime logs in memory; export only safe metadata."""

if not __package__:
    import sys
    from pathlib import Path

    for _parent in Path(__file__).resolve().parents:
        if (_parent / "tools/gateway/__init__.py").is_file():
            sys.path.insert(0, str(_parent))
            break
        if (_parent / "server/tools/gateway/__init__.py").is_file():
            sys.path.insert(0, str(_parent / "server"))
            break


import hashlib
import json
import subprocess
import sys


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: scan_dev05_logs.py COMPOSE_FILE PROJECT")
    result = subprocess.run(
        [
            "docker",
            "--context",
            "desktop-linux",
            "compose",
            "-f",
            sys.argv[1],
            "-p",
            sys.argv[2],
            "logs",
            "--no-color",
            "service_choice_b",
            "worker_choice_b",
        ],
        capture_output=True,
    )
    if result.returncode:
        print(json.dumps({"log_scan": "unavailable", "exit": result.returncode}))
        raise SystemExit(result.returncode)
    raw = result.stdout + result.stderr
    markers = (b"Use lookup for synthetic.", b"Lookup: synthetic", b'"key":"synthetic"')
    found = [index for index, marker in enumerate(markers) if marker in raw]
    report = {
        "log_scan": "PASS" if not found else "CONTENT_LITERAL_FOUND",
        "services": ["service_choice_b", "worker_choice_b"],
        "bytes": len(raw),
        "lines": len(raw.splitlines()),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "matched_marker_indexes": found,
    }
    print(json.dumps(report, sort_keys=True))
    if found:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
