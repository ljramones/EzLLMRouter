"""Run JavaScript runtime regressions against a fresh, locally packed consumer."""

import argparse
import hashlib
from contextlib import ExitStack
import importlib.util
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
    spec = importlib.util.spec_from_file_location("test_network", ROOT / "tools/test_network.py")
    network = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(network)
    with ExitStack() as stack:
        network.block_network(stack, loopback=args.http)
        run_checks(args)


def run_checks(args):
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
        if env.get("EZLLMROUTER_JS_COVERAGE"):
            env["NODE_V8_COVERAGE"] = env["EZLLMROUTER_JS_COVERAGE"]
            coverage = Path(env["EZLLMROUTER_JS_COVERAGE"])
            coverage.mkdir(parents=True, exist_ok=True)
            aliases = {}
            for source in (ROOT / "clients/js").iterdir():
                if source.suffix not in {".cjs", ".mjs"}:
                    continue
                target = installed / source.name
                if target.read_bytes() != source.read_bytes():
                    raise AssertionError("installed SDK bytes differ: " + source.name)
                aliases[target.as_uri()] = {
                    "canonical": source.relative_to(ROOT).as_posix(),
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                }
            (coverage / ("sources-" + consumer.name + ".json")).write_text(json.dumps(aliases))
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
        shutil.copy2(ROOT / "tests/foundation/js-consumer/require.cjs", consumer / "require.cjs")
        inventory = json.loads((ROOT / "tests/javascript_inventory.json").read_text())
        replacements = {
            "repo": str(ROOT),
            "consumer": str(consumer),
            "installed": str(installed),
            "request": str(request),
        }
        commands = [
            [argument.format_map(replacements) for argument in entry["argv"]]
            for entry in inventory.values()
            if entry["runner"] == "client"
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
        failures = []
        for command in commands:
            try:
                subprocess.run(command, env=env, cwd=ROOT, check=True, timeout=120)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
                failures.append(" ".join(command))
        if failures:
            raise SystemExit("Failed installed JavaScript checks: " + "; ".join(failures))
        print("Installed JavaScript client runtime checks passed.")


if __name__ == "__main__":
    main()
