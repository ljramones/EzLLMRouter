"""One entry point for the maintained, offline regression suite and quality gates.

Run `uv run --locked python -m tools.check`. Network/Docker evidence scripts
remain explicit owner-operated workflows, outside this regression command.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import time
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from pathlib import Path
import runpy
import subprocess
import sys
from typing import Any, cast
import unittest
import uuid

from .test_network import block_network as block_network

ROOT = Path(__file__).resolve().parents[1]
OPERATOR_TESTS = (
    "attribution cache_accounting catalogue catalogue_runner connector_availability "
    "crud_update demo attribution_actor attribution_runner profile_upgrade build_target demo_workspace "
    "profile_report_runner reporting reporting_stream team_demo "
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
    "python_actor_recovery completion_preflight completion_continuation completion_runtime completion_identity "
    "completion_supplement first_owner_supplement_followup first_owner_supplement "
    "retrieval_receiver_decode retrieval_tls_receiver_modes "
    "model_identity owned_sender_transport first_write_boundaries"
).split()
SCRIPT_TESTS = (
    "tests/gateway_integration/test_retry_cause.py",
    "tests/gateway_integration/test_work_identity.py",
)
MODULES = (
    "tests.unit.test_container_validation",
    "tests.unit.test_health_failures",
    "tests.unit.test_artifact_retention",
    "tests.unit.test_coverage_gates",
    "tests.unit.test_operator_scheduler",
    "tests.unit.test_authorization_gate_sensitivity.AuthorizationGateSensitivityTests",
    "tests.unit.test_generated_http_framing.AuthenticatedFramingTests",
    "tests.unit.test_lock_audit_failures",
    "tests.unit.test_schema_upgrade_fixtures",
    "tests.unit.test_database_backup",
    "tests.unit.test_maintenance_crashes",
    "tests.unit.test_lineage_traversal",
    "tests.unit.test_security_scanning",
    "tests.unit.test_security_gate_followup",
    "tests.unit.test_secret_scanning",
    "tests.unit.test_bootstrap_pins",
    "tests.unit.test_campaign_interleavings",
    "tests.unit.test_coherent_restore",
    "tests.unit.test_lock_audit",
    "tests.unit.test_process_durability",
    "tests.unit.test_generated_properties.CampaignStateModel",
    "tests.unit.test_generated_properties.CanonicalProperties",
    "tests.unit.test_generated_properties.RegistryStateModel",
    "tests.unit.test_generated_properties.AccountingOrderProperties",
    "tests.unit.test_generated_parsers.GeneratedParserTests",
    "tests.unit.test_generated_test_sensitivity",
    "tests.operator_console.test_authorization_matrix_sockets.SocketPairAuthorizationMatrixTests",
    "tests.operator_console.test_authorization_matrix",
    "tests.operator_console.test_authority_boundaries",
    *("tests.operator_console.test_" + name for name in OPERATOR_TESTS),
    *("tests.development_slice.test_" + name for name in DEVELOPMENT_TESTS),
    *("tests.gateway_integration.test_" + name for name in GATEWAY_TESTS),
    "tests.tool_cycle.test_core",
    "tests.tool_cycle.test_core_sources",
    "tests.tool_cycle.test_core_retention",
    "tests.tool_cycle.test_core_transport",
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
    "tests.unit.test_measurement",
    "tests.unit.test_gateway_lifecycle",
    "tests.unit.test_resource_lifecycle",
    "tests.unit.test_socket_budget",
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
    "tests.unit.test_source_size",
    "tests.unit.test_request_validation",
    "tests.unit.test_domain_imports",
    "tests.unit.test_persistence_recovery",
    "tests.unit.test_structural_cleanup",
)
LOOPBACK_MODULES = (
    "tests.unit.test_operator_scheduler",
    "tests.unit.test_database_backup.DatabaseBackupTests",
    "tests.unit.test_lineage_traversal.LineageTraversalTests",
    "tests.unit.test_socket_budget.SocketBudgetTests",
    "tests.operator_console.test_authorization_matrix_http.LoopbackAuthorizationMatrixTests",
    "tests.development_slice.test_http",
    "tests.operator_console.test_web",
    "tests.operator_console.test_registry_web",
    "tests.operator_console.test_report_http",
    "tests.operator_console.test_integration_credentials.CredentialHTTPTests",
    "tests.operator_console.test_integration_accounting",
    "tests.operator_console.test_integration_accounting_datasets",
    "tests.operator_console.test_integration_accounting_lineage",
    "tests.operator_console.test_integration_accounting_eligibility",
    "tests.operator_console.test_integration_accounting_reports",
    "tests.operator_console.test_integration_accounting_policy",
    "tests.operator_console.test_providers",
    "tests.operator_console.test_socket_lease",
    "tests.development_slice.test_retrieval_http",
    "tests.gateway_integration.test_synchronous_first_owner",
    "tests.gateway_integration.test_owned_tls_sender_transport",
    "tests.gateway_integration.test_first_write_boundaries",
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


def javascript_inventory(root: Path = ROOT) -> dict[str, Any]:
    return dict(json.loads((root / "tests/javascript_inventory.json").read_text()))


FRONTEND_TESTS = tuple(
    Path(path).name
    for path, entry in javascript_inventory().items()
    if entry["runner"] == "console"
)
JAVASCRIPT_SCRIPTS = tuple(
    entry["argv"] for entry in javascript_inventory().values() if entry["runner"] == "offline"
)
QUALITY_PATHS = ("server", "clients", "deploy", "worker", "tools", "tests")
TYPED_PATHS = (
    "server/src/ezllmrouter_server",
    "clients/python/src/ezllmrouter_client",
    "tools/check.py",
    "tools/type_audit.py",
    "tools/test_health.py",
    "tools/artifact_runs.py",
    "tools/branch_coverage.py",
    "tools/coverage_reports.py",
    "tools/coverage_run.py",
    "tools/container_tests.py",
    "tools/docker_validation.py",
    "tools/javascript_coverage.py",
    "tools/security_sast.py",
    "tools/security_lockfiles.py",
    "tools/security_bootstrap.py",
    "tools/security_secrets.py",
    "tools/security_dependencies.py",
    "tools/source_size.py",
    "tools/gateway/paths.py",
    "tests/support.py",
    "deploy/local/command_support.py",
    "deploy/local/filesystem_support.py",
)


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
    registrations: dict[str, list[str | None]] = {}
    errors = []
    for name in modules:
        parts = name.split(".")
        candidates = [Path(*parts[:end]).with_suffix(".py") for end in range(len(parts), 0, -1)]
        registered_path = next((path for path in candidates if (root / path).is_file()), None)
        if registered_path is None:
            errors.append("Missing registered test module: " + name)
        else:
            key = registered_path.as_posix()
            registered.add(key)
            length = len(registered_path.with_suffix("").parts)
            selector = ".".join(parts[length:]) or None
            registrations.setdefault(key, []).append(selector)
    for path, selectors in registrations.items():
        if None in selectors:
            continue
        tree = ast.parse((root / path).read_text())
        aliases = {"TestCase", "unittest.TestCase"}
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "unittest":
                aliases.update(
                    name.asname or name.name for name in node.names if name.name == "TestCase"
                )
            elif isinstance(node, ast.Import):
                aliases.update(
                    (name.asname or name.name) + ".TestCase"
                    for name in node.names
                    if name.name == "unittest"
                )
        classes: set[str] = set()
        definitions = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        while True:
            found = {
                node.name
                for node in definitions
                if any(
                    isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child.name.startswith("test_")
                    for child in node.body
                )
                or any(ast.unparse(base) in aliases | classes for base in node.bases)
            }
            if found <= classes:
                break
            classes.update(found)
        for selector in selectors:
            if selector and "." in selector:
                errors.append("Register the whole test class: " + path + ":" + selector)
        selected = {selector.split(".")[0] for selector in selectors if selector}
        for name in sorted(classes - selected):
            errors.append("Unregistered test class: " + path + ":" + name)
        for name in sorted(selected - classes):
            errors.append("Missing registered test class: " + path + ":" + name)
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


def javascript_inventory_errors(root: Path = ROOT) -> list[str]:
    source = subprocess.check_output(
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
            "tools/accounting/evidence",
        ],
        text=True,
    ).split("\0")
    found = {
        path
        for path in source
        if Path(path).suffix in {".js", ".cjs", ".mjs", ".ts", ".cts", ".mts"}
        and (root / path).is_file()
    }
    inventory = javascript_inventory(root)
    errors = [
        "Unclassified JavaScript/TypeScript file: " + path
        for path in sorted(found - inventory.keys())
    ]
    for path, entry in inventory.items():
        if not (root / path).is_file():
            errors.append("Missing JavaScript inventory file: " + path)
        if entry.get("runner") not in {"console", "client", "offline", "target", "helper"}:
            errors.append("Invalid JavaScript runner: " + path)
        elif entry["runner"] in {"console", "client", "offline"}:
            if (
                not isinstance(entry.get("argv"), list)
                or not entry["argv"]
                or not all(type(arg) is str for arg in entry["argv"])
            ):
                errors.append("Missing JavaScript command: " + path)
        elif not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
            errors.append("Missing JavaScript classification reason: " + path)
    return errors


def run_script(name: str) -> int:
    if name not in SCRIPT_TESTS:
        raise ValueError("unknown regression script")
    sys.argv = [name, "--source-root", str(ROOT)]
    from .test_health import instrumentation, write_script_result

    started, status, instruments = time.perf_counter(), 1, instrumentation()
    try:
        status = _run_script(name)
        return status
    finally:
        write_script_result(
            name,
            time.perf_counter() - started,
            status == 0,
            os.environ.get("EZLLMROUTER_TEST_HEALTH"),
            instruments,
        )


def _run_script(name: str) -> int:
    with ExitStack() as stack:
        auditor = None
        if os.environ.get("EZLLMROUTER_TEST_COVERAGE"):
            from .test_coverage import LineCoverage

            stack.enter_context(LineCoverage(os.environ["EZLLMROUTER_TEST_COVERAGE"]))
        if os.environ.get("EZLLMROUTER_LOCK_AUDIT"):
            from .lock_audit import auditing

            auditor = stack.enter_context(auditing())
        block_network(stack)
        try:
            runpy.run_path(str(ROOT / name), run_name="__main__")
        except SystemExit as error:
            if error.code not in (None, 0):
                return 1
        status = 1 if auditor is not None and auditor.violations else 0
        return status


def run_module(name: str, *, loopback: bool) -> bool:
    # Per-module interpreters isolate environment changes and loaded fixture state.
    health_directory = os.environ.get("EZLLMROUTER_TEST_HEALTH")
    from .test_health import TimedResult, instrumentation, write_module_failure, write_result

    started, instruments = time.perf_counter(), instrumentation()
    with ExitStack() as stack:
        auditor = None
        if os.environ.get("EZLLMROUTER_TEST_COVERAGE"):
            from .test_coverage import LineCoverage

            stack.enter_context(LineCoverage(os.environ["EZLLMROUTER_TEST_COVERAGE"]))
        if os.environ.get("EZLLMROUTER_LOCK_AUDIT"):
            from .lock_audit import auditing

            auditor = stack.enter_context(auditing())
        block_network(stack, loopback=loopback)
        try:
            suite = unittest.defaultTestLoader.loadTestsFromName(name)
        except BaseException:
            write_module_failure(
                name,
                time.perf_counter() - started,
                "load_error",
                health_directory,
                loopback=loopback,
            )
            raise

        result = unittest.TextTestRunner(verbosity=1, resultclass=TimedResult).run(suite)
        violations = auditor.violations if auditor is not None else []
        if violations:
            print(
                f"Shared-lock audit failed: {len(violations)} retained violations", file=sys.stderr
            )
        write_result(
            name,
            cast(TimedResult, result),
            time.perf_counter() - started,
            health_directory,
            loopback=loopback,
            audit_violations=violations,
            instruments=instruments,
        )
        return result.wasSuccessful() and result.testsRun > len(result.skipped) and not violations


def run(argv: list[str]) -> None:
    print("+ " + " ".join(argv), flush=True)
    from .test_network import child_environment

    from .test_health import write_command

    started = time.perf_counter()
    outcome = "failed"
    invocation = uuid.uuid4().hex
    environment = child_environment()
    environment["EZLLMROUTER_TEST_INVOCATION"] = invocation
    try:
        subprocess.run(argv, cwd=ROOT, env=environment, check=True, timeout=180)
        outcome = "passed"
    except subprocess.TimeoutExpired:
        outcome = "timeout"
        raise
    except OSError:
        outcome = "spawn_error"
        raise
    finally:
        from .test_health import has_failed_invocation, write_module_failure

        for flag in ("--test-module", "--test-script"):
            directory = os.environ.get("EZLLMROUTER_TEST_HEALTH")
            if (
                outcome != "passed"
                and flag in argv
                and (outcome == "timeout" or not has_failed_invocation(directory, invocation))
            ):
                identity = argv[argv.index(flag) + 1]
                if flag == "--test-script":
                    identity = "script:" + identity
                write_module_failure(
                    identity,
                    time.perf_counter() - started,
                    outcome,
                    os.environ.get("EZLLMROUTER_TEST_HEALTH"),
                    loopback="--loopback" in argv,
                    invocation=invocation,
                )
                break
        write_command(
            argv, time.perf_counter() - started, outcome, os.environ.get("EZLLMROUTER_TEST_HEALTH")
        )


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="write Python line/conditional-branch and JS SDK/console coverage artifacts",
    )
    parser.add_argument(
        "--coverage-gate",
        action="store_true",
        help="enforce reviewed coverage and critical-exit budgets (requires --coverage)",
    )
    parser.add_argument("--coverage-dir", type=Path, help="fresh directory for tier measurements")
    parser.add_argument(
        "--coverage-merge",
        type=Path,
        help="offline measurement directory to merge with HTTP results",
    )
    parser.add_argument("--health-dir", type=Path, help="test outcome/duration artifact directory")
    parser.add_argument(
        "--health-budget", type=float, help="maximum seconds per Python test module"
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="repeat Python module suites; retain every outcome (no retry pass)",
    )
    parser.add_argument("--tests-only", action="store_true", help="omit Ruff and mypy")
    parser.add_argument(
        "--lock-audit", action="store_true", help="reject blocking work under shared runtime locks"
    )
    parser.add_argument("--loopback", action="store_true", help="also run local HTTP fixtures")
    parser.add_argument("--http-only", action="store_true", help="run only local HTTP fixtures")
    parser.add_argument("--test-module", help=argparse.SUPPRESS)
    parser.add_argument("--test-script", choices=SCRIPT_TESTS, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.lock_audit:
        os.environ["EZLLMROUTER_LOCK_AUDIT"] = "1"
    if args.health_dir is not None:
        os.environ["EZLLMROUTER_TEST_HEALTH"] = str(args.health_dir.resolve())
    if args.test_script:
        return run_script(args.test_script)
    if args.test_module:
        return 0 if run_module(args.test_module, loopback=args.loopback) else 1
    if not 1 <= args.repeat <= 200:
        parser.error("repeat must be between 1 and 200")
    if args.coverage_gate and not args.coverage:
        parser.error("coverage-gate requires coverage")
    if args.coverage_dir is not None and not args.coverage:
        parser.error("coverage-dir requires coverage")
    if args.coverage_merge is not None and not (args.coverage and args.http_only):
        parser.error("coverage-merge requires coverage and http-only")
    if args.health_budget is not None and not 0 < args.health_budget <= 180:
        parser.error("health-budget must be positive and at most 180 seconds")
    from .test_health import instrumentation

    if args.health_budget is not None and (args.coverage or instrumentation()):
        parser.error("health-budget requires an uninstrumented run; omit coverage and lock-audit")
    from .artifact_runs import new_run

    health_parent = ROOT / ".artifacts/test-health"
    health_directory = args.health_dir or new_run(health_parent, "run-", "health")
    health_directory.mkdir(parents=True, exist_ok=True)
    os.environ["EZLLMROUTER_TEST_HEALTH"] = str(health_directory.resolve())
    coverage_directory = None
    coverage_tier = "http" if args.http_only else "combined" if args.loopback else "offline"
    if args.coverage:
        from .coverage_run import prepare

        try:
            coverage_directory = prepare(args.coverage_dir, coverage_tier)
        except ValueError as error:
            parser.error(str(error))
    inventory_errors = test_inventory_errors() + javascript_inventory_errors()
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
            run([sys.executable, "-m", "tools.type_audit"])
            run([sys.executable, "-m", "tools.security_sast"])
            run([sys.executable, "-m", "tools.security_secrets"])
            run([sys.executable, "-m", "tools.security_dependencies"])
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
        for name in modules * args.repeat:
            command = [sys.executable, "-B", "-m", "tools.check", "--test-module", name]
            if (args.loopback or args.http_only) and name in LOOPBACK_MODULES:
                command.append("--loopback")
            try:
                run(command)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
                failures.append(name)
        if not args.http_only:
            for name in SCRIPT_TESTS:
                try:
                    run([sys.executable, "-B", "-m", "tools.check", "--test-script", name])
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
                    failures.append(name)
            for name in FRONTEND_TESTS:
                try:
                    run(["node", "tests/operator_console/" + name])
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
                    failures.append(name)
            for command in JAVASCRIPT_SCRIPTS:
                try:
                    run(list(command))
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
                    failures.append(" ".join(command))
        if coverage_directory is not None:
            from .coverage_run import finish

            errors = finish(
                coverage_directory,
                coverage_tier,
                enforce=args.coverage_gate,
                merge=args.coverage_merge,
            )
            if errors:
                print("\n".join(errors), file=sys.stderr)
                failures.append("coverage budgets")
        from .test_health import budget_errors, instability_errors, summarize

        summary_health = summarize(health_directory)
        unstable = instability_errors(summary_health)
        if unstable:
            print("\n".join(unstable), file=sys.stderr)
            failures.append("unstable test/module outcomes")
        if args.health_budget is not None:
            errors = budget_errors(health_directory, args.health_budget)
            if errors:
                print("\n".join(errors), file=sys.stderr)
                failures.append("module duration budget")
        print("Test health: " + str(health_directory / "summary.json"), flush=True)
        if failures:
            print("Failed checks: " + ", ".join(failures), file=sys.stderr)
            return 1
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as error:
        print(f"Quality check failed: {type(error).__name__}", file=sys.stderr)
        return 1
    print("Quality checks passed.")
    return 0


def main() -> int:
    from .artifact_runs import session

    configured = (
        "EZLLMROUTER_LOCK_AUDIT",
        "EZLLMROUTER_TEST_HEALTH",
        "EZLLMROUTER_TEST_COVERAGE",
        "EZLLMROUTER_JS_COVERAGE",
    )
    saved = {key: os.environ.get(key) for key in configured}
    try:
        with session() as artifacts:
            result = _main()
            artifacts.passed = result == 0
            return result
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
