"""Check credential initialization in an isolated container with CHOWN alone."""

import argparse
import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess


def inside():
    status = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    assert os.getuid() == 0 and int(status["CapEff"].strip(), 16) == 1, "Requires only CAP_CHOWN"
    assert status["NoNewPrivs"].strip() == "1"
    spec = importlib.util.spec_from_file_location(
        "credential_init", "/work/initialize_credentials.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payload = json.dumps(
        {
            "credentials": {"service_token": "t" * 40, "synthetic_provider_key": "k" * 40},
            "operator_password": "p" * 40,
        }
    ).encode()
    directory = Path("/run/ezllmrouter")
    for _ in range(2):
        module.initialize(payload, directory)
        assert sorted(path.name for path in directory.iterdir()) == [
            "credentials.json",
            "operator-password",
        ]
        for path in directory.iterdir():
            info = path.stat()
            assert (info.st_uid, info.st_gid, info.st_mode & 0o777) == (10001, 10001, 0o400)
            try:
                path.read_bytes()
            except PermissionError:
                pass
            else:
                raise AssertionError(
                    "Root without DAC_OVERRIDE must not read the service-owned file"
                )
    print("Credential init: real CHOWN-only creation, replacement and owner-only modes passed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inside", action="store_true")
    args = parser.parse_args()
    if args.inside:
        inside()
        return
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / "deploy/local/profile.py").read_text())
    image = next(
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(name, ast.Name) and name.id == "BASE" for name in node.targets)
    )
    assert "@sha256:" in image
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--platform",
            "linux/arm64",
            "--network",
            "none",
            "--read-only",
            "--user",
            "0:0",
            "--cap-drop",
            "ALL",
            "--cap-add",
            "CHOWN",
            "--security-opt",
            "no-new-privileges:true",
            "--tmpfs",
            "/run/ezllmrouter:rw,nosuid,nodev,noexec,mode=0711",
            "--mount",
            f"type=bind,src={Path(__file__).resolve()},dst=/work/check.py,readonly",
            "--mount",
            f"type=bind,src={root / 'deploy/local/initialize_credentials.py'},dst=/work/initialize_credentials.py,readonly",
            image,
            "python",
            "-I",
            "-S",
            "-B",
            "/work/check.py",
            "--inside",
        ],
        check=True,
        timeout=180,
    )


if __name__ == "__main__":
    main()
