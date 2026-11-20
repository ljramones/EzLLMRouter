"""Bounded, side-effect-free Choice B worker identity handshake."""

import argparse
import json
from pathlib import Path
import re
import socket
import sys
import time

from .choice_b_wire import receive, send


def validate_identity(value, require_empty=True):
    if set(value) != {
        "boundary",
        "litellm",
        "proxy",
        "openai_sdk",
        "httpx",
        "selected_transport",
        "relay_attempt_counts",
    }:
        raise ValueError("worker identity shape")
    counts = value["relay_attempt_counts"]
    if (
        value["boundary"] != "network-disabled LiteLLM ASGI worker"
        or value["selected_transport"] != "RelayTransport"
        or type(counts) is not dict
        or (require_empty and counts)
        or any(
            type(key) is not str
            or not re.fullmatch(r"attempt\.[0-9a-f]{32}", key)
            or type(count) is not int
            or count < 1
            for key, count in counts.items()
        )
    ):
        raise ValueError("worker identity mismatch before submissions")
    for name in ("litellm", "proxy", "openai_sdk", "httpx"):
        row = value[name]
        if (
            type(row) is not dict
            or set(row) != {"path", "sha256"}
            or type(row["path"]) is not str
            or not row["path"].startswith("/")
            or type(row["sha256"]) is not str
            or len(row["sha256"]) != 64
            or any(ch not in "0123456789abcdef" for ch in row["sha256"])
        ):
            raise ValueError("worker module identity malformed: " + name)
    return value


def probe(path, deadline_seconds=50.0, interval_seconds=0.2, require_empty=True):
    if deadline_seconds <= 0 or interval_seconds <= 0:
        raise ValueError("worker readiness bounds")
    end = time.monotonic() + deadline_seconds
    while True:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
                stream.settimeout(min(2.0, max(0.05, end - time.monotonic())))
                stream.connect(str(path))
                send(stream, {"kind": "module_identity"})
                return validate_identity(receive(stream), require_empty=require_empty)
        except (FileNotFoundError, ConnectionRefusedError) as exc:
            if time.monotonic() >= end:
                raise TimeoutError("worker identity socket not ready by deadline") from exc
            time.sleep(min(interval_seconds, max(0.0, end - time.monotonic())))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", type=Path, default=Path("/link/worker.sock"))
    parser.add_argument("--deadline", type=float, default=50.0)
    parser.add_argument("--allow-activity", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            probe(args.socket, args.deadline, require_empty=not args.allow_activity), sort_keys=True
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, EOFError, TimeoutError) as exc:
        print("worker readiness failed: " + type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        raise SystemExit(1)
