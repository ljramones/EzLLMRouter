"""Repeat synchronized race suites, preserving the first failure and replay seed."""

import argparse
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SUITES = (
    ("tests.unit.test_authority_properties", False),
    ("tests.gateway_integration.test_concurrent_transports", True),
    ("tests.unit.test_generated_properties.CampaignStateModel", False),
    ("tests.unit.test_campaign_interleavings", False),
    ("tests.unit.test_database_concurrency", False),
    ("tests.unit.test_operator_sessions", False),
    ("tests.gateway_integration.test_owned_sender_transport", False),
    ("tests.gateway_integration.test_owned_tls_sender_transport", True),
    ("tests.gateway_integration.test_synchronous_first_owner", True),
)


def run(rounds, seed, directory, *, offline_only=False, invoke=subprocess.run):
    if not 1 <= rounds <= 1000:
        raise ValueError("stress rounds must be between 1 and 1000")
    directory.mkdir(parents=True, exist_ok=True)
    rng, records = random.Random(seed), []
    summary = {
        "seed": seed,
        "seed_scope": "suite order and per-round generated model inputs; synchronized races keep explicit event/barrier ordering",
        "requested_rounds": rounds,
        "offline_only": offline_only,
        "runs": records,
        "passed": False,
    }
    try:
        for index in range(rounds):
            case_seed = rng.getrandbits(64)
            suites = [row for row in SUITES if not offline_only or not row[1]]
            rng.shuffle(suites)
            for module, loopback in suites:
                command = [
                    sys.executable,
                    "-B",
                    "-m",
                    "tools.check",
                    "--test-module",
                    module,
                    "--lock-audit",
                    "--health-dir",
                    str(directory / "health"),
                ]
                if loopback:
                    command.append("--loopback")
                started = time.perf_counter()
                entry = {"round": index, "module": module, "seed": case_seed, "passed": False}
                records.append(entry)
                try:
                    with (directory / f"round-{index}-{module}.log").open("w") as log:
                        result = invoke(
                            command,
                            cwd=ROOT,
                            stdout=log,
                            stderr=subprocess.STDOUT,
                            timeout=90,
                            check=False,
                            env={**os.environ, "EZLLMROUTER_TEST_SEED": str(case_seed)},
                        )
                    entry["passed"] = result.returncode == 0
                    entry["outcome"] = "passed" if entry["passed"] else "failed"
                    if not entry["passed"]:
                        return False
                except subprocess.TimeoutExpired:
                    from .test_health import write_module_failure

                    entry["outcome"] = "timeout"
                    write_module_failure(
                        module,
                        time.perf_counter() - started,
                        "timeout",
                        str(directory / "health"),
                        loopback=loopback,
                    )
                    raise
                finally:
                    entry["seconds"] = round(time.perf_counter() - started, 6)
        summary["passed"] = True
        return True
    finally:
        (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20261120)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--offline-only", action="store_true")
    args = parser.parse_args()
    from .artifact_runs import new_run, session

    with session() as artifacts:
        args.output = args.output or new_run(
            ROOT / ".artifacts/concurrency-stress", "run-", "stress"
        )
        status = _main(args)
        artifacts.passed = status == 0
        return status


def _main(args):
    try:
        passed = run(args.rounds, args.seed, args.output, offline_only=args.offline_only)
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        print("Concurrency stress failed: " + type(error).__name__, file=sys.stderr)
        return 1
    print(
        "Concurrency stress "
        + ("passed" if passed else "failed")
        + "; "
        + str(args.output / "summary.json")
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
