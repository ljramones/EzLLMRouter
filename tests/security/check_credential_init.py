"""Qualify Compose's credential permissions and persistent volume in an isolated project."""

import argparse
import ast
import errno
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid


def inside(phase=1, *, reader=False):
    directory = Path("/run/ezllmrouter")
    expected = {
        "credentials": {
            "service_token": ("t" if phase == 1 else "u") * 40,
            "synthetic_provider_key": "k" * 40,
        },
        "operator_password": "p" * 40,
    }
    if reader:
        assert os.getuid() == 10001
        assert json.loads((directory / "credentials.json").read_text()) == expected["credentials"]
        assert (directory / "operator-password").read_text().strip() == expected[
            "operator_password"
        ]
        try:
            (directory / "credentials.json").write_text("must not replace")
        except OSError as error:
            assert error.errno in (errno.EROFS, errno.EACCES)
        else:
            raise AssertionError("Service UID can write its credential input")
        try:
            (directory / "credentials.json").chmod(0o600)
        except OSError as error:
            assert error.errno == errno.EROFS
        else:
            raise AssertionError("Credential mount is not read-only for the service")
        print("Service UID reads the replaced, persisted credential and cannot modify it.")
        return
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
    if phase == 2:
        assert sorted(path.name for path in directory.iterdir()) == [
            "credentials.json",
            "operator-password",
        ], "Named volume did not persist from the first container"
    module.initialize(json.dumps(expected).encode(), directory)
    for path in directory.iterdir():
        info = path.stat()
        assert (info.st_uid, info.st_gid, info.st_mode & 0o777) == (10001, 10001, 0o400)
        try:
            path.read_bytes()
        except PermissionError:
            pass
        else:
            raise AssertionError("Root without DAC_OVERRIDE can read service-owned credentials")
    print(f"CHOWN-only credential initialization phase {phase} passed.")


def base_image(root):
    tree = ast.parse((root / "deploy/local/local_profile.py").read_text())
    image = next(
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(name, ast.Name) and name.id == "BASE" for name in node.targets)
    )
    if "@sha256:" not in image:
        raise ValueError("immutable fixture base image required")
    return image


def validate_configuration(config, project):
    service = config["services"]["credential-init"]
    if service["network_mode"] != "none" or not service["read_only"] or service["user"] != "0:0":
        raise ValueError("credential initializer isolation changed")
    if (
        set(service["cap_drop"]) != {"ALL"}
        or set(service["cap_add"]) != {"CHOWN"}
        or "no-new-privileges:true" not in service["security_opt"]
    ):
        raise ValueError("credential initializer capabilities changed")
    volumes = [volume for volume in service["volumes"] if volume["target"] == "/run/ezllmrouter"]
    if len(volumes) != 1 or volumes[0]["type"] != "volume":
        raise ValueError("credential input must use the Compose named volume")
    if volumes[0]["source"] not in config.get("volumes", {}):
        raise ValueError("credential volume definition is missing")
    for volume in config.get("volumes", {}).values():
        if volume.get("external") or not volume.get("name", "").startswith(project + "_"):
            raise ValueError("fixture must not use an existing or external volume")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inside", action="store_true")
    parser.add_argument("--phase", type=int, choices=(1, 2), default=1)
    parser.add_argument("--reader", action="store_true")
    args = parser.parse_args()
    if args.inside:
        inside(args.phase, reader=args.reader)
        return
    root = Path(__file__).resolve().parents[2]
    image, project = base_image(root), "ezllmrouter-credential-check-" + uuid.uuid4().hex
    env = {
        **os.environ,
        **{
            key: image
            for key in (
                "EZLLMROUTER_SERVICE_IMAGE",
                "EZLLMROUTER_RECEIVER_IMAGE",
                "EZLLMROUTER_WORKER_IMAGE",
                "EZLLMROUTER_PYTHON_IMAGE",
            )
        },
        "EZLLMROUTER_INGRESS_SCRIPT": str(root / "deploy/local/console_ingress.py"),
        "EZLLMROUTER_INGRESS_RESOURCES": str(
            root / "server/src/ezllmrouter_server/runtime_resources.py"
        ),
    }
    with tempfile.TemporaryDirectory(prefix="ezllmrouter-credential-compose-") as directory:
        override = Path(directory) / "fixture.json"
        # Security settings and the credential volume are inherited from the real
        # Compose service. Only the pinned fixture image and read-only test code differ.
        original = [
            "docker",
            "compose",
            "--project-name",
            project,
            "-f",
            str(root / "deploy/local/compose.yaml"),
            "--profile",
            "setup",
        ]
        production = json.loads(
            subprocess.check_output(
                [*original, "config", "--format", "json"], env=env, text=True, timeout=30
            )
        )["services"]["service"]
        selected = [
            volume for volume in production["volumes"] if volume["target"] == "/run/ezllmrouter"
        ]
        if (
            len(selected) != 1
            or not selected[0].get("read_only")
            or production["user"] != "10001:10001"
            or production.get("cap_add")
        ):
            raise ValueError("service credential reader isolation changed")
        reader = {key: production[key] for key in ("user", "read_only", "cap_drop", "security_opt")}
        reader.update(
            platform="linux/arm64",
            image=image,
            pull_policy="missing",
            network_mode="none",
            volumes=[
                selected[0],
                {
                    "type": "bind",
                    "source": str(Path(__file__).resolve()),
                    "target": "/work/check.py",
                    "read_only": True,
                },
            ],
        )
        override.write_text(
            json.dumps(
                {
                    "services": {
                        "credential-init": {
                            "platform": "linux/arm64",
                            "image": image,
                            "pull_policy": "missing",
                            "volumes": [
                                {
                                    "type": "bind",
                                    "source": str(Path(__file__).resolve()),
                                    "target": "/work/check.py",
                                    "read_only": True,
                                },
                                {
                                    "type": "bind",
                                    "source": str(root / "deploy/local/initialize_credentials.py"),
                                    "target": "/work/initialize_credentials.py",
                                    "read_only": True,
                                },
                            ],
                        }
                    }
                }
            )
        )
        saved = json.loads(override.read_text())
        saved["services"]["credential-reader"] = reader
        override.write_text(json.dumps(saved))
        compose = [
            "docker",
            "compose",
            "--project-name",
            project,
            "-f",
            str(root / "deploy/local/compose.yaml"),
            "-f",
            str(override),
            "--profile",
            "setup",
        ]
        config = json.loads(
            subprocess.check_output(
                [*compose, "config", "--format", "json"], env=env, text=True, timeout=30
            )
        )
        validate_configuration(config, project)
        try:
            for phase in (1, 2):
                subprocess.run(
                    [
                        *compose,
                        "run",
                        "--rm",
                        "--no-deps",
                        "credential-init",
                        "python",
                        "-I",
                        "-S",
                        "-B",
                        "/work/check.py",
                        "--inside",
                        "--phase",
                        str(phase),
                    ],
                    env=env,
                    check=True,
                    timeout=180,
                )
            subprocess.run(
                [
                    *compose,
                    "run",
                    "--rm",
                    "--no-deps",
                    "credential-reader",
                    "python",
                    "-I",
                    "-S",
                    "-B",
                    "/work/check.py",
                    "--inside",
                    "--phase",
                    "2",
                    "--reader",
                ],
                env=env,
                check=True,
                timeout=180,
            )
        finally:
            subprocess.run(
                [*compose, "down", "--volumes", "--remove-orphans"], env=env, check=True, timeout=60
            )
    print(
        "Compose credential volume: separate creation/replacement containers and service-UID read passed."
    )


if __name__ == "__main__":
    main()
