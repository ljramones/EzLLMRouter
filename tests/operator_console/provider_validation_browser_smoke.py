#!/usr/bin/env python3
"""Render the explicit provider validation control without submitting model work."""

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


class NoValidationSend:
    principal_id = "svc.demo"

    def run(self, *_args):
        raise AssertionError("browser inspection must not submit model work")


def main():
    suffix = sys.argv[1] if len(sys.argv) == 2 and sys.argv[1] in ("01", "02") else "02"
    result = ROOT / (
        ".artifacts/browser/dev-08/PROVIDER-VALIDATION-BROWSER-RESULT-" + suffix + ".json"
    )
    if result.exists():
        raise SystemExit("validation browser result already exists; preserve prior proof")
    fixture = json.loads((ROOT / "tests/gateway_integration/dev05_fixture.json").read_text())
    server = None
    with tempfile.TemporaryDirectory(prefix="ezllmrouter-validation-browser-") as scratch:
        run = Path(scratch)
        cert, _ = certificate(run)
        store, _, registry, _ = prepare_registry(
            run, fixture, "https://localhost:8766", cert.read_text()
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
                build={"commit": "disposable-validation-browser"},
                web_root=ROOT / "web",
                worker_probe=lambda: {"state": "live"},
                sender_status=lambda: {"state": "live"},
                registry=registry,
                provider_validation=NoValidationSend(),
            )
            threading.Thread(target=server.serve_forever, daemon=True).start()
            before = counters(store)
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
                call(browser, "rowClick", "conn.dev08-controlled", "View")
                wait(
                    browser,
                    "document.querySelector('#view-content')?.textContent.includes('Explicit provider validation')",
                    "validation detail",
                )
                call(browser, "click", "Validate one request…")
                wait(
                    browser,
                    "!!document.querySelector('#view-content form [name=acknowledge_external_send]')",
                    "validation form",
                )
                observed = browser.evaluate(
                    "(()=>{const f=document.querySelector('#view-content form');return {cap:f.querySelector('[name=max_output_tokens]').value,checked:f.querySelector('[name=acknowledge_external_send]').checked,required:f.querySelector('[name=acknowledge_external_send]').required,text:f.textContent.includes('possible input/output token charges')}})()"
                )
                if observed != {"cap": "16", "checked": False, "required": True, "text": True}:
                    raise RuntimeError("explicit validation form is not bounded and unchecked")
                shot = screenshot(browser, run, "provider-validation-form")
                browser.evaluate("document.querySelector('#logout').click();true")
                wait(browser, "!document.querySelector('#login-view').hidden", "signed out")
            after = counters(store)
            if after != before:
                raise RuntimeError("validation browsing created model traffic")
            target = (
                result.parent
                / "screenshots"
                / ("provider-validation-" + suffix + "-" + shot["file"])
            )
            if target.exists():
                raise RuntimeError("screenshot already exists")
            shutil.copy2(run / shot["file"], target)
            record = {
                "status": "PASS",
                "scope": "disposable browser/SQLite; synthetic credential; no provider send",
                "form": observed,
                "model_traffic_before_after": {"before": before, "after": after},
                "screenshot": {"path": str(target.relative_to(ROOT)), "sha256": shot["sha256"]},
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
