"""One entry point for the maintained, offline regression suite and quality gates.

Run `uv run --locked python -m tools.check`. Network/Docker evidence scripts
remain explicit owner-operated workflows, outside this regression command.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
OPERATOR_TESTS = (
    "attribution cache_accounting catalogue catalogue_runner connector_availability "
    "crud_update demo dev07_actor dev07_runner dev08_profile_upgrade dev09_demo_workspace "
    "dev09_profile_run dev09_reporting dev09_team_demo "
    "lifecycle live_audit local_connectors local_connectors_web "
    "model_route personal_campaign prepare projection registry registry_core "
    "usage_update user_management user_management_web"
).split()
DEVELOPMENT_TESTS = (
    "core crypto dev12_accounting_states dev12_correction dev12_late_evidence "
    "dev12_plan dev12_reporting dev12_sdk dev12_service_states dev12_store "
    "dev12_successor_contract"
).split()
GATEWAY_TESTS = (
    "guard provider_guard provider_plan dev12_guard_timeout core_bridge choice_b "
    "dev05 dev05_capture provider_worker_diagnostic dev12_first_write"
).split()
SCRIPT_TESTS = (
    "tests/gateway_integration/test_retry_cause.py",
    "tests/gateway_integration/test_work_identity.py",
)
MODULES = (
    *("tests.operator_console.test_" + name for name in OPERATOR_TESTS),
    *("tests.development_slice.test_" + name for name in DEVELOPMENT_TESTS),
    *("tests.gateway_integration.test_" + name for name in GATEWAY_TESTS),
    "tests.tool_cycle.test_core",
    "tests.operator_console.test_integration_credentials.CredentialTests",
    "tests.unit.test_release_safety",
    "tests.unit.test_security_boundaries",
    "tests.unit.test_deployment_safety",
    "tests.unit.test_startup_recovery",
    "tests.unit.test_accounting_recovery",
    "tests.unit.test_python_client_safety",
    "tests.client_parity.test_python_client",
    "tests.tool_cycle.test_python_client",
    "tests.unit.test_gateway_packaging",
    "tests.unit.test_secret_rotation",
    "tests.unit.test_database",
    "tests.unit.test_operator_routes",
)
LOOPBACK_MODULES = (
    "tests.development_slice.test_http",
    "tests.operator_console.test_web",
    "tests.operator_console.test_registry_web",
    "tests.operator_console.test_dev09_http",
    "tests.operator_console.test_integration_credentials.CredentialHTTPTests",
    "tests.operator_console.test_integration_accounting",
    "tests.operator_console.test_providers",
    "tests.operator_console.test_socket_lease",
)
FRONTEND_TESTS = (
    "test_console_navigation.cjs",
    "test_users_view.cjs",
    "test_local_connectors_view.cjs",
    "test_catalogue_view.cjs",
    "test_activity_usage_view.cjs",
    "test_crud_view.cjs",
    "test_dev09_provider_index.cjs",
)
TYPED_FILES = (
    "server/src/duranki_server/private_files.py",
    "server/src/duranki_server/observability.py",
    "server/src/duranki_server/database.py",
    "server/src/duranki_server/schema.py",
    "tools/check.py",
    "clients/python/src/duranki_client/_http.py",
    "clients/python/src/duranki_client/_json.py",
)


def denied_network(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("network/socket operation in the offline regression suite")


def block_network(stack: ExitStack) -> None:
    for attribute in ("connect", "connect_ex", "bind"):
        stack.enter_context(patch.object(socket.socket, attribute, denied_network))
    stack.enter_context(patch.object(socket, "getaddrinfo", denied_network))


def run_script(name: str) -> int:
    if name not in SCRIPT_TESTS:
        raise ValueError("unknown regression script")
    sys.argv = [name, "--source-root", str(ROOT)]
    with ExitStack() as stack:
        block_network(stack)
        try:
            runpy.run_path(str(ROOT / name), run_name="__main__")
        except SystemExit as error:
            return 0 if error.code in (None, 0) else 1
    return 0


def run_module(name: str, *, loopback: bool) -> bool:
    # Each module runs in a separate interpreter: legacy fixture path imports
    # and environment changes cannot contaminate another module's tests.
    sys.path.insert(0, str(ROOT / "server/src"))
    sys.path.insert(0, str(ROOT / "clients/python/src"))
    # Historical test fixtures use plain sibling imports; isolate and define
    # their search path here instead of depending on unittest's working dir.
    sys.path.insert(0, str(ROOT / "tests/development_slice"))
    sys.path.insert(0, str(ROOT / "tests/gateway_integration"))
    with ExitStack() as stack:
        if not loopback:
            block_network(stack)
        suite = unittest.defaultTestLoader.loadTestsFromName(name)
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        return result.wasSuccessful() and result.testsRun > 0


def run(argv: list[str]) -> None:
    print("+ " + " ".join(argv), flush=True)
    subprocess.run(argv, cwd=ROOT, check=True, timeout=180)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tests-only", action="store_true", help="omit Ruff and mypy")
    parser.add_argument("--loopback", action="store_true", help="also run local HTTP fixtures")
    parser.add_argument("--http-only", action="store_true", help="run only local HTTP fixtures")
    parser.add_argument("--test-module", help=argparse.SUPPRESS)
    parser.add_argument("--test-script", choices=SCRIPT_TESTS, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.test_script:
        return run_script(args.test_script)
    if args.test_module:
        return 0 if run_module(args.test_module, loopback=args.loopback) else 1
    try:
        node_version = subprocess.check_output(["node", "--version"], text=True).strip().lstrip("v")
        if node_version != (ROOT / ".nvmrc").read_text().strip().lstrip("v"):
            print("Use the Node version in .nvmrc (for example, run `nvm use`).", file=sys.stderr)
            return 1
        if not args.tests_only and not args.http_only:
            run(
                [
                    sys.executable,
                    "-m",
                    "ruff",
                    "check",
                    "server/src",
                    "clients/python/src",
                    "deploy/local",
                    "worker",
                    "tools",
                ]
            )
            run([sys.executable, "-m", "ruff", "format", "--check", *TYPED_FILES])
            run([sys.executable, "-m", "mypy", *TYPED_FILES])
        # Check all application JavaScript syntax, not only modules reached by a view fixture.
        if not args.http_only:
            for path in sorted((ROOT / "web").glob("*.js")):
                run(["node", "--check", str(path.relative_to(ROOT))])
            run(["bash", "-n", "start.sh"])
        modules = (
            LOOPBACK_MODULES
            if args.http_only
            else MODULES + (LOOPBACK_MODULES if args.loopback else ())
        )
        failures = []
        for name in modules:
            command = [sys.executable, "-B", "-m", "tools.check", "--test-module", name]
            if (args.loopback or args.http_only) and name in LOOPBACK_MODULES:
                command.append("--loopback")
            try:
                run(command)
            except subprocess.CalledProcessError:
                failures.append(name)
        if not args.http_only:
            for name in SCRIPT_TESTS:
                run([sys.executable, "-B", "-m", "tools.check", "--test-script", name])
            for name in FRONTEND_TESTS:
                run(["node", "tests/operator_console/" + name])
        if failures:
            print("Failed modules: " + ", ".join(failures), file=sys.stderr)
            return 1
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as error:
        print(f"Quality check failed: {type(error).__name__}", file=sys.stderr)
        return 1
    print("Quality checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
