#!/usr/bin/env python3
"""Disposable actual-browser DEV-08 management proof; no model dispatch."""

from __future__ import annotations

if not __package__:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import hashlib
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

from deploy.local.browser_cdp import HeadlessChrome
from deploy.local.crud_browser import HELPERS, call, wait, wait_initial_page, screenshot
from ezllmrouter_server.operator_projection import OperatorProjection
from ezllmrouter_server.operator_web import serve
from ezllmrouter_server.registry import Registry
from tests.operator_console.test_providers import ProviderTests


class NeverRun:
    def run(self, *_):
        raise AssertionError("provider management browser must not launch model work")


def counters(store):
    return {
        name: store.db.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
        for name in ("submissions", "intents", "guard_dispatches")
    }


def main():
    suffix = sys.argv[1] if len(sys.argv) == 2 and sys.argv[1] in ("01", "04", "05", "06") else "01"
    result_path = ROOT / (
        ".artifacts/browser/dev-08/PROVIDER-LOCAL-BROWSER-RESULT-" + suffix + ".json"
    )
    if result_path.exists():
        raise SystemExit("provider browser result already exists; preserve prior proof")
    fixture_test = ProviderTests("test_distinct_native_tls_inventory_and_readiness")
    fixture_test.setUp()
    server = None
    try:
        registry, store = fixture_test.registry, fixture_test.store
        fixture = json.loads((ROOT / "tools/gateway/evidence/dev05_fixture.json").read_text())
        catalogue_ref = "catalogue.operator.provider-browser"
        registry.mutate(
            "owner.local",
            {
                "operation_id": "op.browser.catalogue",
                "action": "register_catalogue",
                "subject": catalogue_ref,
                "expected_revision": 0,
                "data": {
                    "display_name": "Controlled provider test model",
                    "vendor": "Test only",
                    "family": "Controlled TLS",
                    "api_model_id": "model-test",
                    "model_version": "test-v1",
                    "owner": "owner.local",
                    "capabilities": ["text"],
                    "context_window": None,
                    "max_output": None,
                    "notes": "Disposable browser association",
                    "price": {
                        "snapshot_id": "browser.test.v1",
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
            build={"commit": "local-dev08-disposable-proof"},
            web_root=ROOT / "web",
            worker_probe=lambda: {"state": "live"},
            sender_status=lambda: {"state": "live"},
            registry=registry,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        before = counters(store)
        with tempfile.TemporaryDirectory(prefix="ezllmrouter-provider-browser-") as scratch:
            run = Path(scratch)
            with HeadlessChrome(run, f"http://127.0.0.1:{port}/") as browser:
                wait_initial_page(browser)
                browser.evaluate(HELPERS)
                browser.evaluate(
                    "document.querySelector('#password').value='"
                    + "p" * 40
                    + "';document.querySelector('#login-form').requestSubmit();true"
                )
                wait(browser, "!document.querySelector('#workspace').hidden", "signed-in workspace")
                call(browser, "navigate", "providers")
                call(browser, "click", "Add connection")
                call(browser, "submit", {"adapter_id": "vllm.openai-compatible.v1"})
                wait(
                    browser,
                    "!!document.querySelector('#view-content form [name=connection_id]')",
                    "typed vLLM form",
                )
                call(
                    browser,
                    "submit",
                    {
                        "connection_id": "conn.browser-test",
                        "display_name": "Controlled lab",
                        "site": "Disposable local TLS",
                        "origin": fixture_test.origin,
                        "owner": "owner.local",
                        "engine_version": "vllm.test",
                        "ca_pem": fixture_test.cert,
                    },
                )
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('conn.browser-test')",
                    "connection row",
                )
                shots = [screenshot(browser, run, "connection-created")]
                call(browser, "rowClick", "conn.browser-test", "View")
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('Controlled lab')",
                    "connection detail",
                )
                call(browser, "click", "Edit label")
                call(browser, "submit", {"display_name": "Edited controlled lab"})
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('Edited controlled lab')",
                    "edited detail",
                )
                call(browser, "click", "Replace credential")
                call(browser, "submit", {"secret": "test-provider-key-123456"})
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('Stored · version 1')",
                    "credential state",
                )
                if browser.evaluate("document.body.innerText.includes('test-provider-key-123456')"):
                    raise RuntimeError("credential leaked into rendered browser text")
                shots.append(screenshot(browser, run, "credential-masked"))
                call(browser, "click", "Test access")
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('credential accepted for model listing only')",
                    "access observation",
                )
                call(browser, "click", "Refresh inventory")
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('model-test')",
                    "inventory observation",
                )
                call(browser, "click", "Check readiness")
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('vllm health 200 not model capacity')",
                    "readiness observation",
                )
                browser.evaluate(
                    "[...document.querySelectorAll('#view-content .panel')].find(x=>x.querySelector('h2')?.textContent==='Scoped observations')?.scrollIntoView();true"
                )
                shots.append(screenshot(browser, run, "scoped-observations"))
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
                        "deployment_id": "deployment.browser-test",
                        "model_ref": catalogue_ref,
                        "serving_id": "model-test",
                        "site": "Disposable local TLS",
                    },
                )
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('deployment.browser-test')",
                    "model association",
                )
                shots.append(screenshot(browser, run, "model-associated"))
                call(browser, "click", "Disable")
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('disabled')",
                    "disabled connection",
                )
                call(browser, "click", "Archive…")
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('archived')",
                    "archived connection",
                )
                shots.append(screenshot(browser, run, "connection-archived"))
                browser.evaluate("document.querySelector('#logout').click();true")
                wait(browser, "!document.querySelector('#login-view').hidden", "signed out")
                signed_out = browser.evaluate("fetch('/operator/v1/connections').then(x=>x.status)")
                if signed_out != 401:
                    raise RuntimeError("signed-out connection API remained accessible")
            after = counters(store)
            if before != after:
                raise RuntimeError("browser connection management created model traffic")
            reopened = Registry(store, fixture_test.authority, provider_vault=fixture_test.vault)
            connection = reopened.connection("conn.browser-test")
            deployments = reopened.deployments("conn.browser-test")
            observations = reopened.observations("conn.browser-test")
            if (
                connection["status"] != "archived"
                or len(deployments) != 1
                or deployments[0]["execution_approved"]
                or len(observations) != 3
            ):
                raise RuntimeError("connection restart readback mismatch")
            screenshots = []
            screenshot_root = result_path.parent / "screenshots"
            screenshot_root.mkdir(parents=True, exist_ok=True)
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
            "scope": "disposable SQLite + actual Chrome + controlled TLS endpoint",
            "connection": "conn.browser-test",
            "connection_status_after_reopen": connection["status"],
            "deployment": deployments[0]["deployment_id"],
            "execution_approved": False,
            "observations": [item["operation"] + ":" + item["state"] for item in observations],
            "model_traffic_before_after": {"before": before, "after": after},
            "credential_visible_in_browser": False,
            "signed_out_http": signed_out,
            "screenshots": screenshots,
            "source_sha256": hashlib.sha256(
                (ROOT / "web/providers_view.js").read_bytes()
            ).hexdigest(),
        }
        result_path.parent.mkdir(parents=True, exist_ok=True)
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
