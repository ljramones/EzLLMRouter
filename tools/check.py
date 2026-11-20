"""One entry point for the maintained, offline regression suite and quality gates.

Run `uv run --locked python -m tools.check`. Network/Docker evidence scripts
remain explicit owner-operated workflows, outside this regression command.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from pathlib import Path
import ipaddress
import runpy
import socket
import subprocess
import sys
from typing import Any
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
OPERATOR_TESTS = (
    "attribution cache_accounting catalogue catalogue_runner connector_availability "
    "crud_update demo attribution_actor attribution_runner profile_upgrade build_target demo_workspace "
    "profile_report_runner reporting team_demo "
    "lifecycle live_audit local_connectors local_connectors_web "
    "model_route personal_campaign prepare projection registry registry_core "
    "usage_update user_management user_management_web"
).split()
DEVELOPMENT_TESTS = (
    "core crypto retrieval_accounting_states retrieval_correction retrieval_late_evidence "
    "retrieval_plans retrieval_reporting retrieval_client retrieval_service_states retrieval_store "
    "retrieval_contract native_adapter"
).split()
GATEWAY_TESTS = (
    "guard provider_guard provider_plan compressed_responses retrieval_guard_timeout core_bridge choice_b "
    "guarded_tool_execution runtime_capture provider_worker_diagnostic retrieval_first_write "
    "python_actor_recovery completion_preflight "
    "completion_supplement first_owner_supplement_followup first_owner_supplement "
    "retrieval_receiver_decode retrieval_tls_receiver_modes "
    "model_identity owned_sender_transport"
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
    "tests.gateway_integration.test_worker_ready.WorkerReadyOfflineTests",
    "tests.operator_console.test_integration_credentials.CredentialTests",
    "tests.unit.test_release_safety",
    "tests.unit.test_security_boundaries",
    "tests.unit.test_deployment_safety",
    "tests.unit.test_deployment_cleanup",
    "tests.unit.test_startup_recovery",
    "tests.unit.test_accounting_recovery",
    "tests.unit.test_python_client_safety",
    "tests.unit.test_client_consistency",
    "tests.unit.test_runtime_cleanup",
    "tests.unit.test_tooling_hygiene",
    "tests.client_parity.test_python_client",
    "tests.client_parity.test_actor_logic",
    "tests.client_parity.test_fixture_routes",
    "tests.tool_cycle.test_python_client",
    "tests.tool_cycle.test_receiver",
    "deploy.local.test_dev08_integrated_run",
    "tests.unit.test_gateway_packaging",
    "tests.unit.test_secret_rotation",
    "tests.unit.test_certificate_constraints",
    "tests.unit.test_database",
    "tests.unit.test_operator_routes",
    "tests.unit.test_http_structure",
    "tests.unit.test_shared_server_logic",
    "tests.unit.test_security_polish",
    "tests.unit.test_encryption_maintenance",
    "tests.client_languages.test_contracts",
    "tests.playwright.test_server",
    "tests.unit.test_check_inventory",
    "tests.unit.test_gateway_lifecycle",
    "tests.unit.test_resource_lifecycle",
    "tests.unit.test_correctness_cases",
    "tests.unit.test_gateway_runtime_safety",
    "tests.unit.test_observation_retention",
    "tests.unit.test_database_concurrency",
    "tests.unit.test_database_batch",
    "tests.unit.test_operator_sessions",
    "tests.unit.test_provider_transport",
    "tests.unit.test_client_deadlines",
    "tests.unit.test_provision_recovery",
    "tests.unit.test_quality_gates",
)
LOOPBACK_MODULES = (
    "tests.development_slice.test_http",
    "tests.operator_console.test_web",
    "tests.operator_console.test_registry_web",
    "tests.operator_console.test_report_http",
    "tests.operator_console.test_integration_credentials.CredentialHTTPTests",
    "tests.operator_console.test_integration_accounting",
    "tests.operator_console.test_providers",
    "tests.operator_console.test_socket_lease",
    "tests.development_slice.test_retrieval_http",
    "tests.gateway_integration.test_synchronous_first_owner",
    "tests.gateway_integration.test_owned_tls_sender_transport",
    "tests.gateway_integration.test_readiness",
    "tests.gateway_integration.test_worker_ready.WorkerReadyTests",
    "tests.operator_console.test_retrieval_operator_http",
    "tests.operator_console.test_ingress",
    "tests.gateway_integration.test_installed_client_boundary",
)
EXCLUDED_TESTS = {
    "tests/gateway_integration/test_freshness_interface.py": "Executed by deploy/local/Dockerfile.service validation with the frozen wheel mount and AnyIO 4.15.1; the development lock uses 4.16.0.",
    "tests/gateway_integration/test_alt_handler.py": "Build-time isolation check in the frozen LiteLLM image; needs that reviewed runtime.",
    "tests/gateway_integration/test_cache_frozen_usage.py": "Executed by deploy/local/Dockerfile.worker with its read-only validation mount and the frozen LiteLLM wheels.",
    "tests/gateway_integration/test_provider_worker_target.py": "Standalone frozen-worker discriminator invoked by Dockerfile.worker; not a unittest module.",
    "tests/gateway_integration/test_run10_held_timeout.py": "Explicit evidence audit requiring --repo, --runtime and --timeout-source from a retained run.",
}
FRONTEND_TESTS = (
    "test_console_navigation.cjs",
    "test_users_view.cjs",
    "test_local_connectors_view.cjs",
    "test_catalogue_view.cjs",
    "test_activity_usage_view.cjs",
    "test_crud_view.cjs",
    "test_provider_index.cjs",
)
QUALITY_PATHS = ("server", "clients", "deploy", "worker", "tools", "tests")
TYPED_PATHS = (
    "server/src/ezllmrouter_server/identifiers.py",
    "server/src/ezllmrouter_server/identity.py",
    "server/src/ezllmrouter_server/external_identity.py",
    "server/src/ezllmrouter_server/_metadata.py",
    "server/src/ezllmrouter_server/gateway/provider_reply.py",
    "server/src/ezllmrouter_server/formatting.py",
    "server/src/ezllmrouter_server/json_validation.py",
    "server/src/ezllmrouter_server/errors.py",
    "server/src/ezllmrouter_server/states.py",
    "server/src/ezllmrouter_server/instance_lock.py",
    "server/src/ezllmrouter_server/operator_http/policy.py",
    "server/src/ezllmrouter_server/private_files.py",
    "server/src/ezllmrouter_server/observability.py",
    "server/src/ezllmrouter_server/database.py",
    "server/src/ezllmrouter_server/schema.py",
    "tools/check.py",
    "tools/gateway/paths.py",
    "tests/support.py",
    "deploy/local/command_support.py",
    "deploy/local/filesystem_support.py",
    "clients/python/src/ezllmrouter_client",
    "server/src/ezllmrouter_server/repositories",
    "server/src/ezllmrouter_server/provider_adapters.py",
    "server/src/ezllmrouter_server/operator_http/application.py",
    "server/src/ezllmrouter_server/operator_http/common.py",
    "server/src/ezllmrouter_server/operator_http/routing.py",
)


def denied_network(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("network/socket operation in the offline regression suite")


def test_inventory_errors(
    root: Path = ROOT,
    modules: Sequence[str] = MODULES + LOOPBACK_MODULES,
    scripts: Sequence[str] = SCRIPT_TESTS,
    excluded: Mapping[str, str] = EXCLUDED_TESTS,
) -> list[str]:
    source_files = subprocess.check_output(
        [
            "git",
            "-C",
            str(root),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            "tests",
            "deploy/local",
        ],
        text=True,
    ).split("\0")
    discovered = {
        path for path in source_files if Path(path).match("test_*.py") and (root / path).is_file()
    }
    registered = set(scripts)
    errors = []
    for name in modules:
        parts = name.split(".")
        candidates = [Path(*parts[:end]).with_suffix(".py") for end in range(len(parts), 0, -1)]
        registered_path = next((path for path in candidates if (root / path).is_file()), None)
        if registered_path is None:
            errors.append("Missing registered test module: " + name)
        else:
            registered.add(registered_path.as_posix())
    for path in sorted(discovered - registered - excluded.keys()):
        errors.append("Unclassified test file: " + path)
    for path, reason in excluded.items():
        if not reason.strip():
            errors.append("Missing exclusion reason: " + path)
        if path not in discovered:
            errors.append("Missing excluded test file: " + path)
        if path in registered:
            errors.append("Test is both registered and excluded: " + path)
    for path in sorted(set(scripts) - discovered):
        errors.append("Missing registered test script: " + path)
    return errors


def block_network(stack: ExitStack, *, loopback: bool = False) -> None:
    def local(host: object) -> bool:
        try:
            name = host.decode("ascii") if isinstance(host, bytes) else host
            return (
                name == "localhost"
                or isinstance(name, str)
                and ipaddress.ip_address(name).is_loopback
            )
        except (ValueError, UnicodeError):
            return False

    def guarded(operation: Callable[..., Any]) -> Callable[..., Any]:
        def call(connection: socket.socket, address: Any, *args: Any, **kwargs: Any) -> Any:
            if connection.family != socket.AF_UNIX and (
                not isinstance(address, tuple) or not local(address[0])
            ):
                denied_network()
            return operation(connection, address, *args, **kwargs)

        return call

    resolve = socket.getaddrinfo

    def local_resolve(host: Any, *args: Any, **kwargs: Any) -> Any:
        if not local(host):
            denied_network()
        addresses = resolve(host, *args, **kwargs)
        if any(not local(address[4][0]) for address in addresses):
            denied_network()
        return addresses

    for attribute in ("connect", "connect_ex", "bind"):
        operation = guarded(getattr(socket.socket, attribute)) if loopback else denied_network
        stack.enter_context(patch.object(socket.socket, attribute, operation))
    stack.enter_context(
        patch.object(socket, "getaddrinfo", local_resolve if loopback else denied_network)
    )


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
    # Per-module interpreters isolate environment changes and loaded fixture state.
    with ExitStack() as stack:
        block_network(stack, loopback=loopback)
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
    inventory_errors = test_inventory_errors()
    if inventory_errors:
        print("\n".join(inventory_errors), file=sys.stderr)
        return 1
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
                    *QUALITY_PATHS,
                ]
            )
            run([sys.executable, "-m", "ruff", "format", "--check", *QUALITY_PATHS])
            run([sys.executable, "-m", "mypy", *TYPED_PATHS])
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
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
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
