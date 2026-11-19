"""Run JavaScript runtime regressions against a fresh, locally packed consumer."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--http", action="store_true")
    args = parser.parse_args()
    artifacts = ROOT / ".artifacts"
    artifacts.mkdir(exist_ok=True)
    env = {
        **os.environ,
        "npm_config_cache": str(ROOT / ".cache/npm"),
        "npm_config_audit": "false",
        "npm_config_fund": "false",
        "npm_config_update_notifier": "false",
    }
    with tempfile.TemporaryDirectory(prefix="javascript-client-", dir=artifacts) as directory:
        consumer = Path(directory)
        packed = subprocess.check_output(
            [
                "npm",
                "pack",
                str(ROOT / "clients/js"),
                "--offline",
                "--ignore-scripts",
                "--pack-destination",
                directory,
                "--json",
            ],
            env=env,
            text=True,
            timeout=60,
        )
        archive = consumer / json.loads(packed)[0]["filename"]
        (consumer / "package.json").write_text('{"private":true}')
        subprocess.run(
            [
                "npm",
                "install",
                "--prefix",
                directory,
                "--offline",
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
                "--no-package-lock",
                str(archive),
            ],
            env=env,
            check=True,
            timeout=60,
        )
        installed = consumer / "node_modules/@cognitivedynamics/ezllmrouter-client"
        env.update(
            NODE_PATH=str(consumer / "node_modules"),
            EZLLMROUTER_INSTALLED_CLIENT="1",
            DEV12_JS_CLIENT_DIR=str(installed),
            EZLLMROUTER_JS_CONSUMER=directory,
        )
        vectors = (
            ROOT
            / "tests/fixtures/contracts/wp-a-03-c01/EZLLMROUTER-WP-A-VECTORS-v0.3-CORRECTION-01.json"
        )
        request = ROOT / "tests/development_slice/request.json"
        for name, files in {
            "tool": ("tests/tool_cycle/test_js_client.cjs",),
            "actor": (
                "tests/client_parity/test_actor_logic.cjs",
                "tests/client_parity/integration_js.cjs",
                "tests/client_parity/scenarios.json",
            ),
        }.items():
            target = consumer / name
            target.mkdir()
            for source in files:
                shutil.copy2(ROOT / source, target / Path(source).name)
            shutil.copy2(vectors, target / "vectors.json")
            shutil.copy2(request, target / "request.json")
        commands = [
            ["node", str(ROOT / "tests/development_slice/test_client.cjs")],
            ["node", str(ROOT / "tests/development_slice/test_dev12_sdk.cjs")],
            ["node", str(consumer / "tool/test_js_client.cjs")],
            ["node", str(consumer / "actor/test_actor_logic.cjs")],
            ["node", str(ROOT / "tests/gateway_integration/test_dev05_js_actor.cjs")],
            ["node", str(ROOT / "tests/security/node_client_transport.cjs"), directory],
        ]
        if args.http:
            commands = [
                [
                    os.sys.executable,
                    "-I",
                    "-S",
                    str(ROOT / "tests/client_languages/http_fixture.py"),
                    "--client",
                    "js",
                ]
            ]
        for command in commands:
            subprocess.run(command, env=env, cwd=ROOT, check=True, timeout=120)
        print("Installed JavaScript client runtime checks passed.")


if __name__ == "__main__":
    main()
