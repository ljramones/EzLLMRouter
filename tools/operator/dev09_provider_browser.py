#!/usr/bin/env python3
"""One-use disposable Chrome check of DEV-09 provider setup and reference prices."""

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
for relative in ("server/src", "deploy/local", "tests/operator_console"):
    sys.path.insert(0, str(ROOT / relative))

from deploy.local.browser_cdp import HeadlessChrome
from deploy.local.crud_browser import HELPERS, call, wait, wait_initial_page, screenshot
from ezllmrouter_server.operator_projection import OperatorProjection
from ezllmrouter_server.operator_web import serve
from tools.operator.provider_browser_smoke import NeverRun, counters
from tests.operator_console.test_providers import ProviderTests


def main():
    suffix = sys.argv[1] if len(sys.argv) == 2 and sys.argv[1] in ("01", "02") else "01"
    result = ROOT / (".artifacts/browser/dev-09/PROVIDER-BROWSER-RESULT-" + suffix + ".json")
    if result.exists():
        raise SystemExit(f"DEV-09 provider browser result already exists: {result}")
    fixture_test = ProviderTests("test_distinct_native_tls_inventory_and_readiness")
    fixture_test.setUp()
    server = None
    try:
        registry, store = fixture_test.registry, fixture_test.store
        registry.controlled_provider_proof = True  # Disposable loopback TLS only.
        registry.mutate(
            "owner.local",
            {
                "operation_id": "op.dev09.controlled",
                "action": "create_connection",
                "subject": "conn.dev09-controlled",
                "expected_revision": 0,
                "data": {
                    "display_name": "Controlled API setup",
                    "adapter_id": "openai.responses.v1",
                    "settings": fixture_test.settings(),
                    "owner": "owner.local",
                },
            },
        )
        registry.mutate(
            "owner.local",
            {
                "operation_id": "op.dev09.reference",
                "action": "register_catalogue",
                "subject": "catalogue.operator.dev09",
                "expected_revision": 0,
                "data": {
                    "display_name": "Controlled reference model",
                    "vendor": "OpenAI",
                    "family": "Test reference",
                    "api_model_id": "model-test",
                    "model_version": "test-v1",
                    "owner": "owner.local",
                    "capabilities": ["text"],
                    "context_window": None,
                    "max_output": None,
                    "notes": "Disposable research reference",
                    "price": {
                        "snapshot_id": "dev09.reference.v1",
                        "source_title": "Test reference",
                        "source_url": "https://example.org/test",
                        "bands": [
                            {
                                "label": "Test rate",
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
        fixture = json.loads((ROOT / "tools/gateway/evidence/dev05_fixture.json").read_text())
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = serve(
            "127.0.0.1",
            port,
            projection=OperatorProjection(store, "svc.demo"),
            runner=NeverRun(),
            password="p" * 40,
            fixture=fixture,
            build={"commit": "dev09-provider-disposable"},
            web_root=ROOT / "web",
            worker_probe=lambda: {"state": "live"},
            sender_status=lambda: {"state": "live"},
            registry=registry,
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        before = counters(store)
        with tempfile.TemporaryDirectory(prefix="ezllmrouter-dev09-provider-") as scratch:
            run = Path(scratch)
            with HeadlessChrome(run, f"http://127.0.0.1:{port}/") as browser:
                wait_initial_page(browser)
                browser.evaluate(HELPERS)
                browser.evaluate(
                    "window.confirm=()=>true;document.querySelector('#password').value='"
                    + "p" * 40
                    + "';document.querySelector('#login-form').requestSubmit();true"
                )
                wait(browser, "!document.querySelector('#workspace').hidden", "workspace")
                call(browser, "navigate", "source_providers")
                call(browser, "click", "Add provider")
                call(browser, "submit", {"adapter_id": "openai.responses.v1"})
                wait(
                    browser,
                    "!!document.querySelector('form [name=display_name]')",
                    "provider setup form",
                )
                if (
                    browser.evaluate("document.querySelector('form [name=origin]').value")
                    != "https://api.openai.com"
                ):
                    raise RuntimeError("approved OpenAI origin was not preselected")
                call(
                    browser,
                    "submit",
                    {
                        "display_name": "New disconnected setup",
                        "connection_id": "conn.dev09-new",
                        "site": "Test account",
                        "owner": "owner.local",
                    },
                )
                wait(browser, "location.hash.includes('conn.dev09-new')", "source return")
                if registry.connection("conn.dev09-new")["credential_state"] != "absent":
                    raise RuntimeError("setup creation saved an implicit credential")
                call(browser, "navigate", "providers")
                call(browser, "rowClick", "conn.dev09-controlled", "View")
                wait(
                    browser,
                    "document.querySelector('#view-content').textContent.includes('Not set up')",
                    "unchecked setup",
                )
                wait(
                    browser,
                    "document.querySelector('#view-content').textContent.includes('Usage & Costs · Controlled API setup')",
                    "connection scoped cost panel",
                )
                call(browser, "click", "Set up API access")
                browser.evaluate("document.querySelector('[name=test_access]').checked=true;true")
                call(browser, "submit", {"secret": "test-key-123456789"})
                wait(
                    browser,
                    "document.querySelector('#view-content').textContent.includes('API access verified')",
                    "verified access",
                )
                if browser.evaluate(
                    "document.querySelector('#view-content').textContent.includes('test-key-123456789')"
                ):
                    raise RuntimeError("credential appeared in operator view")
                call(browser, "click", "Discover models")
                wait(
                    browser,
                    "document.querySelector('#view-content').textContent.includes('model-test')",
                    "explicit inventory",
                )
                verified = screenshot(browser, run, "verified-api-setup")
                call(browser, "click", "Replace credential")
                browser.evaluate("document.querySelector('[name=test_access]').checked=true;true")
                call(browser, "submit", {"secret": "invalid-key-123456789"})
                wait(
                    browser,
                    "document.querySelector('#view-content').textContent.includes('Credential rejected')",
                    "credential rejection",
                )
                if browser.evaluate(
                    "document.querySelector('#view-content').textContent.includes('invalid-key-123456789')"
                ):
                    raise RuntimeError("rejected credential appeared in operator view")
                call(browser, "navigate", "models")
                call(browser, "rowClick", "catalogue.operator.dev09", "View")
                wait(
                    browser,
                    "document.querySelector('#view-content').textContent.includes('One observed price')",
                    "one-point chart",
                )
                call(browser, "click", "Edit EzLLMRouter settings")
                call(
                    browser,
                    "submit",
                    {"display_name": "Local reference alias", "notes": "Local note"},
                )
                wait(
                    browser,
                    "document.querySelector('#view-content').textContent.includes('Local reference alias')",
                    "saved local alias",
                )
                call(browser, "click", "Edit EzLLMRouter settings")
                call(browser, "fill", "display_name", "Discarded alias")
                call(browser, "click", "Cancel")
                wait(
                    browser,
                    "[...document.querySelectorAll('#view-content button')].some(x=>x.textContent.trim()==='Correct recorded price data')",
                    "cancelled edit",
                )
                if (
                    registry.model("catalogue.operator.dev09")["display_name"]
                    != "Local reference alias"
                ):
                    raise RuntimeError("cancel mutated model")
                call(browser, "click", "Correct recorded price data")
                call(
                    browser,
                    "submit",
                    {
                        "source_title": "Corrected test source",
                        "source_url": "https://example.org/correction",
                        "band_0_input": "3",
                        "band_0_output": "4",
                    },
                )
                wait(
                    browser,
                    "document.querySelectorAll('.price-history-row').length===2",
                    "two-point chart",
                )
                if not browser.evaluate(
                    "[...document.querySelectorAll('.price-history-chart + div tr')].length===3"
                ):
                    raise RuntimeError("chart and exact price table disagree")
                price = screenshot(browser, run, "price-history-and-local-settings")
                browser.evaluate("document.querySelector('#logout').click();true")
                wait(browser, "!document.querySelector('#login-view').hidden", "sign out")
            after = counters(store)
            if after != before:
                raise RuntimeError("provider browser workflow launched model work")
            requests = [path for path, _ in fixture_test.server.requests if path == "/v1/models"]
            if len(requests) != 3:
                raise RuntimeError(
                    f"expected access, discovery and rejection checks; got {len(requests)}"
                )
            result.parent.mkdir(parents=True, exist_ok=True)
            screenshots = []
            for shot in (verified, price):
                target = result.parent / "screenshots" / ("dev09-" + suffix + "-" + shot["file"])
                target.parent.mkdir(exist_ok=True)
                if target.exists():
                    raise RuntimeError(f"screenshot already exists: {target}")
                shutil.copy2(run / shot["file"], target)
                screenshots.append(
                    {"path": str(target.relative_to(ROOT)), "sha256": shot["sha256"]}
                )
            record = {
                "status": "PASS",
                "scope": "disposable Chrome, SQLite and controlled loopback TLS",
                "source_commit": __import__("subprocess")
                .check_output(["git", "rev-parse", "HEAD"], cwd=ROOT)
                .decode()
                .strip(),
                "source_dirty": True,
                "api_checks_and_discovery": len(requests),
                "states": ["Not set up", "API access verified", "Credential rejected"],
                "price_observations": 2,
                "model_traffic_before_after": {"before": before, "after": after},
                "connection_usage_panel": True,
                "screenshots": screenshots,
                "source_hashes": {
                    name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                    for name in (
                        "web/providers_view.js",
                        "web/crud_view.js",
                        "web/source_pages.js",
                        "server/src/ezllmrouter_server/registry.py",
                    )
                },
            }
            result.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
            print(json.dumps(record, sort_keys=True))
    finally:
        if server:
            server.shutdown()
            server.server_close()
            server.operator_jobs.shutdown(wait=True)
        fixture_test.doCleanups()


if __name__ == "__main__":
    main()
