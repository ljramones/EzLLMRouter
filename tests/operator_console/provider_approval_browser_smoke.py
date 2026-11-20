#!/usr/bin/env python3
"""Browser approval controls with fake credential and zero provider/model calls."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
sys.path.insert(0, str(ROOT / "deploy/local"))
sys.path.insert(0, str(ROOT / "tests/operator_console"))

from browser_cdp import HeadlessChrome
from crud_browser import HELPERS, call, wait, wait_initial_page, screenshot
from ezllmrouter_server.operator_projection import OperatorProjection
from ezllmrouter_server.operator_web import serve
from ezllmrouter_server.registry import Registry
from provider_browser_smoke import NeverRun, counters
from test_providers import ProviderTests


def main():
    suffix = sys.argv[1] if len(sys.argv) == 2 and sys.argv[1] in ("02", "03", "04") else "04"
    result_path = ROOT / (
        ".artifacts/browser/dev-08/PROVIDER-APPROVAL-BROWSER-RESULT-" + suffix + ".json"
    )
    if result_path.exists():
        raise SystemExit("provider approval result already exists; preserve prior proof")
    fixture_test = ProviderTests("test_distinct_native_tls_inventory_and_readiness")
    fixture_test.setUp()
    server = None
    try:
        registry, store = fixture_test.registry, fixture_test.store
        registry.provider_execution_ready = (
            True  # Controlled candidate only; persistent service remains gated.
        )
        fixture = json.loads((ROOT / "tests/gateway_integration/dev05_fixture.json").read_text())
        model_ref = "catalogue.operator.provider-approval"
        registry.mutate(
            "owner.local",
            {
                "operation_id": "op.approval.catalogue",
                "action": "register_catalogue",
                "subject": model_ref,
                "expected_revision": 0,
                "data": {
                    "display_name": "Controlled Responses model",
                    "vendor": "Test only",
                    "family": "Responses",
                    "api_model_id": "model-test",
                    "model_version": "test-v1",
                    "owner": "owner.local",
                    "capabilities": ["text"],
                    "context_window": None,
                    "max_output": None,
                    "notes": "Disposable provider approval UI proof",
                    "price": {
                        "snapshot_id": "browser.reference.v1",
                        "source_title": "Test placeholder",
                        "source_url": "https://example.org/test",
                        "bands": [
                            {
                                "label": "Test",
                                "conditions": {},
                                "rates_usd_per_1000000_tokens": {
                                    "input_uncached": "1",
                                    "output": "2",
                                    "input_cached": None,
                                },
                            }
                        ],
                    },
                },
            },
        )
        projection = OperatorProjection(store, "svc.demo")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = serve(
            "127.0.0.1",
            port,
            projection=projection,
            runner=NeverRun(),
            password="p" * 40,
            fixture=fixture,
            build={"commit": "local-dev08-approval-proof"},
            web_root=ROOT / "web",
            worker_probe=lambda: {"state": "live"},
            sender_status=lambda: {"state": "live"},
            registry=registry,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        before = counters(store)
        with tempfile.TemporaryDirectory(
            prefix="ezllmrouter-provider-approval-browser-"
        ) as scratch:
            run = Path(scratch)
            with HeadlessChrome(run, f"http://127.0.0.1:{port}/") as browser:
                wait_initial_page(browser)
                browser.evaluate(HELPERS)
                browser.evaluate(
                    "document.querySelector('#password').value='"
                    + "p" * 40
                    + "';document.querySelector('#login-form').requestSubmit();true"
                )
                wait(browser, "!document.querySelector('#workspace').hidden", "workspace")
                call(browser, "navigate", "providers")
                call(browser, "click", "Add connection")
                call(browser, "submit", {"adapter_id": "openai.responses.v1"})
                wait(
                    browser,
                    "!!document.querySelector('#view-content form [name=connection_id]')",
                    "OpenAI form",
                )
                call(
                    browser,
                    "submit",
                    {
                        "connection_id": "conn.approval-browser",
                        "display_name": "Controlled Responses connection",
                        "site": "Controlled account",
                        "origin": "https://api.openai.com",
                        "owner": "owner.local",
                    },
                )
                call(browser, "rowClick", "conn.approval-browser", "View")
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('Controlled Responses connection')",
                    "connection detail",
                )
                call(browser, "click", "Replace credential")
                call(browser, "submit", {"secret": "test-provider-key-123456"})
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('Stored · version 1')",
                    "credential stored",
                )
                call(browser, "click", "Activate connection")
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('active')",
                    "active connection",
                )
                call(browser, "click", "Associate model")
                wait(
                    browser,
                    "!!document.querySelector('#view-content form [name=deployment_id]')",
                    "association form",
                )
                call(
                    browser,
                    "submit",
                    {
                        "deployment_id": "deployment.approval-browser",
                        "model_ref": model_ref,
                        "serving_id": "model-test",
                        "site": "Controlled account",
                    },
                )
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('Create execution configuration')",
                    "association",
                )
                call(browser, "click", "Create execution configuration")
                wait(
                    browser,
                    "!!document.querySelector('#view-content form [name=configuration_ref]')",
                    "configuration form",
                )
                call(
                    browser,
                    "submit",
                    {
                        "configuration_ref": "cfg.provider.approval-browser",
                        "display_name": "Controlled Responses route",
                        "owner": "owner.local",
                        "purposes": "execution",
                        "task_classes": "class.demo",
                    },
                )
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('cfg.provider.approval-browser')",
                    "draft configuration",
                )
                shots = [screenshot(browser, run, "provider-configuration-draft")]
                call(browser, "click", "cfg.provider.approval-browser")
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('Controlled Responses route')",
                    "configuration detail",
                )
                call(browser, "click", "Update prices")
                call(
                    browser,
                    "submit",
                    {"price_version": "browser.approved.v1", "input": "1", "output": "2"},
                )
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('browser.approved.v1')",
                    "approved price",
                )
                # The separate source-page browser proof exercises this control in the UI.
                # This older approval walkthrough needs the new exact source permission
                # before it can reach its intended configuration/grant assertions.
                registry.mutate(
                    "owner.local",
                    {
                        "operation_id": "op.approval.source-allow",
                        "action": "set_source_permissions",
                        "subject": "conn.approval-browser",
                        "expected_revision": 0,
                        "data": {
                            "allowed": True,
                            "items": [{"serving_id": "model-test", "expected_revision": 0}],
                        },
                    },
                )
                call(browser, "click", "Enable")
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('enabled')",
                    "enabled configuration",
                )
                shots.append(screenshot(browser, run, "provider-configuration-enabled"))
                call(browser, "navigate", "users")
                call(browser, "toggle", "Show test fixtures")
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('svc.demo')",
                    "fixture identity",
                )
                call(browser, "rowClick", "svc.demo", "Manage model access")
                wait(
                    browser,
                    "!!document.querySelector('#view-content form [name=configuration_ref]')",
                    "grant form",
                )
                call(
                    browser,
                    "submit",
                    {
                        "configuration_ref": "cfg.provider.approval-browser",
                        "status": "active",
                        "purposes": "execution",
                        "task_classes": "class.demo",
                    },
                )
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('Explicit model access')",
                    "grant detail",
                )
                query = "'/operator/v1/access/explain?principal_id=svc.demo&configuration_ref=cfg.provider.approval-browser&purpose=execution&task_class=class.demo'"
                allowed = browser.evaluate(
                    "fetch(" + query + ").then(x=>x.json()).then(x=>x.reason)"
                )
                if allowed != "ALLOWED":
                    raise RuntimeError("approved route not admitted: " + str(allowed))
                shots.append(screenshot(browser, run, "provider-grant"))
                call(browser, "navigate", "providers")
                call(browser, "rowClick", "conn.approval-browser", "View")
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('Controlled Responses connection')",
                    "connection detail",
                )
                call(browser, "click", "Disable")
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('disabled')",
                    "disabled connection",
                )
                denied = browser.evaluate(
                    "fetch(" + query + ").then(x=>x.json()).then(x=>x.reason)"
                )
                if denied != "TRANSPORT_UNAVAILABLE":
                    raise RuntimeError("disabled route remained admitted: " + str(denied))
                shots.append(screenshot(browser, run, "provider-disabled"))
                browser.evaluate("document.querySelector('#logout').click();true")
                wait(browser, "!document.querySelector('#login-view').hidden", "signed out")
            after = counters(store)
            if after != before:
                raise RuntimeError("approval browsing created model traffic")
            reopened = Registry(
                store,
                fixture_test.authority,
                provider_vault=fixture_test.vault,
                provider_execution_ready=True,
            )
            connection = reopened.connection("conn.approval-browser")
            config = reopened.model("cfg.provider.approval-browser")
            grant = reopened.grant("svc.demo", "cfg.provider.approval-browser")
            if (
                connection["status"] != "disabled"
                or config["status"] != "enabled"
                or grant["status"] != "active"
            ):
                raise RuntimeError("approval restart readback mismatch")
            screenshot_root = result_path.parent / "screenshots"
            screenshot_root.mkdir(parents=True, exist_ok=True)
            screenshots = []
            for item in shots:
                target = screenshot_root / ("provider-local-" + suffix + "-" + item["file"])
                if target.exists():
                    raise RuntimeError("screenshot evidence already exists")
                shutil.copy2(run / item["file"], target)
                screenshots.append(
                    {"path": str(target.relative_to(ROOT)), "sha256": item["sha256"]}
                )
        safe = {
            "status": "PASS",
            "scope": "disposable browser/SQLite; fake credential; no external call",
            "connection": "conn.approval-browser",
            "configuration": "cfg.provider.approval-browser",
            "price_version": "browser.approved.v1",
            "grant": "svc.demo",
            "access_before_disable": allowed,
            "access_after_disable": denied,
            "model_traffic_before_after": {"before": before, "after": after},
            "screenshots": screenshots,
        }
        result_path.write_text(json.dumps(safe, indent=2, sort_keys=True) + "\n")
        print(json.dumps(safe, sort_keys=True))
    finally:
        if server:
            server.shutdown()
            server.server_close()
            server.operator_jobs.shutdown(wait=True)
        fixture_test.doCleanups()


if __name__ == "__main__":
    main()
