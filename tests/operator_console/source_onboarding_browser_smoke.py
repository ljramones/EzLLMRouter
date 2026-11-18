#!/usr/bin/env python3
"""Disposable Chrome proof of source registration and controlled inventory; no generation."""
from __future__ import annotations

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

from browser_cdp import HeadlessChrome
from crud_browser import HELPERS, call, wait, wait_initial_page, screenshot
from duranki_server.operator_projection import OperatorProjection
from duranki_server.operator_web import serve
from provider_browser_smoke import NeverRun, counters
from test_providers import ProviderTests


def main():
    suffix = sys.argv[1] if len(sys.argv) == 2 and sys.argv[1] in ("01", "02") else "02"
    result = ROOT / ("docs/development/dev-08/SOURCE-ONBOARDING-BROWSER-RESULT-" + suffix + ".json")
    if result.exists():
        raise SystemExit("source onboarding result already exists; preserve prior proof")
    fixture_test = ProviderTests("test_distinct_native_tls_inventory_and_readiness")
    fixture_test.setUp()
    server = None
    try:
        registry, store = fixture_test.registry, fixture_test.store
        fixture = json.loads((ROOT / "tests/gateway_integration/dev05_fixture.json").read_text())
        registry.mutate("owner.local", {"operation_id": "op.onboard.reference", "action": "register_catalogue",
            "subject": "catalogue.operator.onboard", "expected_revision": 0,
            "data": {"display_name": "Controlled reference model", "vendor": "OpenAI", "family": "Test reference",
                "api_model_id": "model-test", "model_version": "test-v1", "owner": "owner.local",
                "capabilities": ["text"], "context_window": None, "max_output": None,
                "notes": "Disposable research reference; no authenticated provider inventory",
                "price": {"snapshot_id": "onboard.reference.v1", "source_title": "Test reference",
                    "source_url": "https://example.org/test", "bands": [{"label": "Test rate",
                    "conditions": {}, "rates_usd_per_1000000_tokens": {
                        "input_uncached": "1", "output": "2", "input_cached": None}}]}}})
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = serve("127.0.0.1", port, projection=OperatorProjection(store, "svc.demo"),
            runner=NeverRun(), password="p" * 40, fixture=fixture,
            build={"commit": "source-onboarding-disposable"}, web_root=ROOT / "web",
            worker_probe=lambda: {"state": "live"}, sender_status=lambda: {"state": "live"},
            registry=registry)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        before = counters(store)
        with tempfile.TemporaryDirectory(prefix="duranki-source-onboarding-") as scratch:
            run = Path(scratch)
            with HeadlessChrome(run, f"http://127.0.0.1:{port}/") as browser:
                wait_initial_page(browser)
                browser.evaluate(HELPERS)
                browser.evaluate("window.confirm=()=>true;document.querySelector('#password').value='" +
                    "p" * 40 + "';document.querySelector('#login-form').requestSubmit();true")
                wait(browser, "!document.querySelector('#workspace').hidden", "workspace")
                call(browser, "navigate", "source_providers")
                call(browser, "click", "OpenAI")
                wait(browser, "location.hash==='#/providers/openai'", "provider detail")
                wait(browser, "document.querySelector('#view-content')?.textContent.includes('Controlled reference model')", "provider reference inventory")
                if not browser.evaluate("document.querySelector('#view-content')?.textContent.includes('$1 input / $2 output · USD per 1M tokens')"):
                    raise RuntimeError("provider reference list lacks numeric unit prices")
                call(browser, "click", "Add account / connection")
                if browser.evaluate("document.querySelector('form [name=origin]')?.value") != "https://api.openai.com":
                    raise RuntimeError("provider account form did not preselect its API context")
                call(browser, "submit", {"connection_id": "conn.onboard-provider",
                    "display_name": "Controlled provider account", "site": "Test account",
                    "origin": "https://api.openai.com", "owner": "owner.local"})
                wait(browser, "location.hash.includes('/connections/conn.onboard-provider')", "new provider source route")
                wait(browser, "document.querySelector('#view-content')?.textContent.includes('Controlled provider account')", "new provider detail")
                if registry.connection("conn.onboard-provider")["status"] != "draft":
                    raise RuntimeError("provider registration unexpectedly activated a connection")
                shots = [screenshot(browser, run, "provider-account-created")]
                browser.evaluate("history.back();true")
                wait(browser, "location.hash==='#/providers/openai'", "provider overview")
                wait(browser, "document.querySelector('#view-content')?.textContent.includes('Controlled reference model')", "reference row")
                shots.append(screenshot(browser, run, "provider-reference-prices"))
                browser.evaluate("[...document.querySelectorAll('#view-content tr')].find(x=>x.textContent.includes('Controlled reference model'))?.querySelector('button')?.click();true")
                wait(browser, "document.querySelector('#view-title')?.textContent==='Model & pricing detail'", "reference detail")
                wait(browser, "!!document.querySelector('.reference-source-list')", "reference sources")
                if browser.evaluate("getComputedStyle(document.querySelector('.reference-source-list')).display") != "grid":
                    raise RuntimeError("reference sources were not visually separated")
                call(browser, "click", "← Source models")
                wait(browser, "location.hash==='#/providers/openai'&&document.querySelector('#view-title')?.textContent==='OpenAI'", "source-aware back")

                call(browser, "navigate", "source_private")
                call(browser, "click", "Register installation")
                if not browser.evaluate("document.querySelector('#view-content')?.textContent.includes('vllm.openai-compatible.v1')"):
                    raise RuntimeError("private installation form lacks adapter context")
                call(browser, "submit", {"connection_id": "conn.onboard-private",
                    "display_name": "Controlled private installation", "site": "Private test installation",
                    "origin": fixture_test.origin, "owner": "owner.local",
                    "engine_version": "vllm.test", "ca_pem": fixture_test.cert})
                wait(browser, "location.hash==='#/private-hosting/conn.onboard-private'", "private source route")
                wait(browser, "document.querySelector('#view-content')?.textContent.includes('Controlled private installation')", "private source detail")
                call(browser, "click", "Connection & Credentials")
                wait(browser, "[...document.querySelectorAll('#view-content button')].some(x=>x.textContent.trim()==='Replace credential')", "private connection tab")
                call(browser, "click", "Replace credential")
                call(browser, "submit", {"secret": "test-private-key-123456"})
                wait(browser, "location.hash==='#/private-hosting/conn.onboard-private'&&document.querySelector('#view-content')?.textContent.includes('Stored · version 1')", "private credential return")
                call(browser, "click", "Activate connection")
                wait(browser, "document.querySelector('#view-content')?.textContent.includes('active')", "private active")
                call(browser, "click", "Models")
                wait(browser, "document.querySelector('#view-content')?.textContent.includes('discovery never run')", "private models tab")
                call(browser, "click", "Refresh inventory")
                wait(browser, "document.querySelector('#view-content')?.textContent.includes('discovery complete')&&document.querySelector('#view-content')?.textContent.includes('model-test')", "complete controlled inventory")
                if registry.source_inventory("conn.onboard-private")["items"][0]["allowed"]:
                    raise RuntimeError("discovery unexpectedly allowed a model")
                shots.append(screenshot(browser, run, "private-discovered-disallowed"))
                call(browser, "rowClick", "model-test", "Allow")
                wait(browser, "document.querySelector('#view-content')?.textContent.includes('Allowed')", "private allowed")
                if not registry.source_inventory("conn.onboard-private")["items"][0]["allowed"]:
                    raise RuntimeError("source Allow was not persisted")
                shots.append(screenshot(browser, run, "private-allowed"))
                call(browser, "rowClick", "model-test", "Disallow")
                wait(browser, "document.querySelector('#view-content')?.textContent.includes('Disallowed')", "private disallowed")
                if registry.source_inventory("conn.onboard-private")["items"][0]["allowed"]:
                    raise RuntimeError("source Disallow was not persisted")

                call(browser, "navigate", "source_labs")
                call(browser, "click", "Register lab / serving connection")
                call(browser, "submit", {"connection_id": "conn.onboard-lab",
                    "display_name": "Controlled lab pool", "site": "Office test lab",
                    "origin": fixture_test.origin, "owner": "owner.local",
                    "engine_version": "vllm.test", "ca_pem": fixture_test.cert})
                wait(browser, "location.hash==='#/office-labs/Office%20test%20lab/connections/conn.onboard-lab'", "lab source route")
                wait(browser, "document.querySelector('#view-content')?.textContent.includes('Controlled lab pool')", "lab source detail")
                shots.append(screenshot(browser, run, "lab-connection-created"))
                call(browser, "navigate", "providers")
                wait(browser, "document.querySelector('#view-content')?.textContent.includes('conn.onboard-provider')&&document.querySelector('#view-content')?.textContent.includes('conn.onboard-private')&&document.querySelector('#view-content')?.textContent.includes('conn.onboard-lab')", "central connection readback")
                shots.append(screenshot(browser, run, "central-connections"))
                browser.evaluate("document.querySelector('#logout').click();true")
                wait(browser, "!document.querySelector('#login-view').hidden", "sign out")
            after = counters(store)
            if after != before:
                raise RuntimeError("onboarding browser generated model traffic")
            inventory_gets = [path for path, _ in fixture_test.server.requests if path == "/v1/models"]
            if len(inventory_gets) != 1:
                raise RuntimeError("expected one explicit controlled inventory request")
            screenshot_root = result.parent / "screenshots"
            screenshot_root.mkdir(exist_ok=True)
            saved = []
            for shot in shots:
                target = screenshot_root / ("source-onboarding-" + suffix + "-" + shot["file"])
                if target.exists():
                    raise RuntimeError("screenshot already exists")
                shutil.copy2(run / shot["file"], target)
                saved.append({"path": str(target.relative_to(ROOT)), "sha256": shot["sha256"]})
            record = {"status": "PASS", "scope": "disposable Chrome/SQLite and controlled loopback TLS; test credential",
                "browser_build_label": "source-onboarding-disposable", "runtime_profile_modified": False,
                "source_asset_sha256": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                    for path in ("web/source_pages.js", "web/providers_view.js", "web/crud_view.js", "web/app.css")},
                "connections": ["conn.onboard-provider", "conn.onboard-private", "conn.onboard-lab"],
                "controlled_inventory_gets": len(inventory_gets), "inventory_completeness": "complete",
                "initial_source_permission": "disallowed", "source_permission_edit": "allow_then_disallow",
                "source_aware_back": "PASS", "reference_rates_numeric": True,
                "model_traffic_before_after": {"before": before, "after": after}, "screenshots": saved}
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
