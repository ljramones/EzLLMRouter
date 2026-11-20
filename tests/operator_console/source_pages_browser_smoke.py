#!/usr/bin/env python3
"""Disposable Chrome proof of source navigation and permission without model traffic."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[2]
for relative in (
    "server/src",
    "deploy/local",
    "tests/operator_console",
    "tests/gateway_integration",
    "tests/development_slice",
):
    sys.path.insert(0, str(ROOT / relative))

from browser_cdp import HeadlessChrome
from crud_browser import HELPERS, call, wait, wait_initial_page, screenshot
from dev08_integrated import certificate, prepare_registry
from ezllmrouter_server.operator_projection import OperatorProjection
from ezllmrouter_server.operator_web import serve
from provider_browser_smoke import NeverRun, counters


def change(registry, action, subject, expected, data, operation):
    return registry.mutate(
        "owner.local",
        {
            "operation_id": operation,
            "action": action,
            "subject": subject,
            "expected_revision": expected,
            "data": data,
        },
    )


def main():
    suffix = sys.argv[1] if len(sys.argv) == 2 and sys.argv[1] in ("01", "02") else "02"
    result = ROOT / (".artifacts/browser/dev-08/SOURCE-PAGES-BROWSER-RESULT-" + suffix + ".json")
    if result.exists():
        raise SystemExit("source pages result already exists; preserve prior proof")
    fixture = json.loads((ROOT / "tests/gateway_integration/dev05_fixture.json").read_text())
    server = None
    with tempfile.TemporaryDirectory(prefix="ezllmrouter-source-pages-") as scratch:
        run = Path(scratch)
        cert, _ = certificate(run)
        store, authority, registry, config = prepare_registry(
            run, fixture, "https://localhost:8766", cert.read_text()
        )
        for kind, connection_id, site in (
            ("private_cloud", "conn.private-example", "Private installation"),
            ("office_lab", "conn.lab-example", "Office lab A"),
        ):
            change(
                registry,
                "create_connection",
                connection_id,
                0,
                {
                    "display_name": site,
                    "adapter_id": "vllm.openai-compatible.v1",
                    "settings": {
                        "origin": "https://localhost:8766",
                        "location": kind,
                        "site": site,
                        "ca_pem": cert.read_text(),
                        "engine_version": "vllm.test",
                    },
                    "owner": "owner.local",
                },
                "op.source.browser." + kind,
            )
            change(
                registry,
                "associate_deployment",
                connection_id,
                1,
                {
                    "deployment_id": "deployment." + kind,
                    "model_ref": "catalogue.operator.dev08-controlled",
                    "serving_id": "test-response-model",
                    "site": site,
                    "status": "catalogued",
                },
                "op.source.browser.associate." + kind,
            )
        projection = OperatorProjection(store, "svc.demo")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        try:
            server = serve(
                "127.0.0.1",
                port,
                projection=projection,
                runner=NeverRun(),
                password="p" * 40,
                fixture=fixture,
                build={"commit": "source-pages-disposable"},
                web_root=ROOT / "web",
                worker_probe=lambda: {"state": "live"},
                sender_status=lambda: {"state": "live"},
                registry=registry,
            )
            threading.Thread(target=server.serve_forever, daemon=True).start()
            before = counters(store)
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
                call(browser, "click", "OpenAI")
                wait(browser, "location.hash==='#/providers/openai'", "provider route")
                call(browser, "click", "Controlled TLS fixture")
                wait(
                    browser,
                    "location.hash.includes('/connections/conn.dev08-controlled')",
                    "selected account route",
                )
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('test-response-model')",
                    "provider inventory",
                )
                shots = [screenshot(browser, run, "provider-source-models")]
                call(browser, "rowClick", "test-response-model", "Disallow")
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('Disallowed')",
                    "disallowed model",
                )
                denied = registry.explain(
                    "svc.demo", config["configuration_ref"], "execution", "class.demo"
                )["reason"]
                if denied != "SOURCE_MODEL_DISALLOWED":
                    raise RuntimeError("source disallow did not override recorded grant")
                shots.append(screenshot(browser, run, "provider-disallowed"))
                browser.evaluate("history.back();true")
                wait(browser, "location.hash==='#/providers/openai'", "browser back")
                browser.evaluate("location.reload();true")
                wait_initial_page(browser)
                browser.evaluate(HELPERS)
                browser.evaluate(
                    "window.confirm=()=>true;document.querySelector('#password').value='"
                    + "p" * 40
                    + "';document.querySelector('#login-form').requestSubmit();true"
                )
                wait(
                    browser,
                    "document.querySelector('#view-title')?.textContent==='OpenAI'",
                    "provider reload route",
                )
                call(browser, "navigate", "source_private")
                call(browser, "click", "Private installation")
                wait(
                    browser,
                    "location.hash==='#/private-hosting/conn.private-example'",
                    "private route",
                )
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('manual association')",
                    "private manual inventory",
                )
                shots.append(screenshot(browser, run, "private-installation"))
                call(browser, "navigate", "source_labs")
                call(browser, "click", "Office lab A")
                wait(browser, "location.hash==='#/office-labs/Office%20lab%20A'", "lab site route")
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('test-response-model')",
                    "supported lab model",
                )
                shots.append(screenshot(browser, run, "office-lab-supported"))
                call(browser, "navigate", "users")
                call(browser, "toggle", "Show test fixtures")
                call(browser, "rowClick", "svc.demo", "Manage model access")
                wait(
                    browser,
                    "!!document.querySelector('#view-content form [name=configuration_ref]')",
                    "grant picker",
                )
                options = browser.evaluate(
                    "[...document.querySelectorAll('select[name=configuration_ref] optgroup')].map(x=>({label:x.label,options:[...x.querySelectorAll('option')].map(o=>o.textContent)}))"
                )
                if not any(
                    "Provider / OpenAI" in group["label"]
                    and any("blocked; removal only" in item for item in group["options"])
                    for group in options
                ):
                    raise RuntimeError("blocked provider grant was not grouped and visible")
                shots.append(screenshot(browser, run, "blocked-grant-picker"))
                browser.evaluate("document.querySelector('#logout').click();true")
                wait(browser, "!document.querySelector('#login-view').hidden", "signed out")
            after = counters(store)
            if after != before:
                raise RuntimeError("source navigation or permission changed model traffic")
            screenshot_root = result.parent / "screenshots"
            screenshot_root.mkdir(exist_ok=True)
            saved = []
            for shot in shots:
                target = screenshot_root / ("source-pages-" + suffix + "-" + shot["file"])
                if target.exists():
                    raise RuntimeError("screenshot already exists")
                shutil.copy2(run / shot["file"], target)
                saved.append({"path": str(target.relative_to(ROOT)), "sha256": shot["sha256"]})
            record = {
                "status": "PASS",
                "scope": "disposable browser/SQLite; synthetic credential; zero inference",
                "routes": [
                    "#/providers/openai/connections/conn.dev08-controlled",
                    "#/private-hosting/conn.private-example",
                    "#/office-labs/Office%20lab%20A",
                ],
                "back_and_reload": "PASS",
                "source_disallow_reason": denied,
                "blocked_grant_groups": options,
                "model_traffic_before_after": {"before": before, "after": after},
                "screenshots": saved,
            }
            result.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
            print(json.dumps(record, sort_keys=True))
        finally:
            if server:
                server.shutdown()
                server.server_close()
                server.operator_jobs.shutdown(wait=True)
            store.close()


if __name__ == "__main__":
    main()
