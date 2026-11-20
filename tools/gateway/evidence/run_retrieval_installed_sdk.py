"""Install the private wheel offline and exercise the public client under test."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


def main():
    wheel = Path(os.environ["DEV12_PY_CLIENT_WHEEL"])
    if not wheel.is_file():
        raise SystemExit("private wheel absent")
    with TemporaryDirectory(prefix="dev12-installed-sdk-") as directory:
        subprocess.run(
            (
                sys.executable,
                "-I",
                "-B",
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                "--target",
                directory,
                str(wheel),
            ),
            check=True,
        )
        environment = {**os.environ, "DEV12_PY_CLIENT_TARGET": directory}
        subprocess.run(
            (
                sys.executable,
                "-I",
                "-B",
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests/development_slice",
                "-p",
                "test_retrieval_client.py",
                "-v",
            ),
            env=environment,
            check=True,
        )


if __name__ == "__main__":
    main()
