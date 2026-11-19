#!/usr/bin/env python3
"""Disposable DEV-10 normal provider-page credential journey; no generation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
for relative in ("server/src", "deploy/local", "tests/operator_console"):
    sys.path.insert(0, str(ROOT / relative))

from browser_cdp import HeadlessChrome
from crud_browser import HELPERS, call, wait, wait_initial_page, screenshot
from duranki_server.operator_projection import OperatorProjection
from duranki_server.operator_web import serve
from duranki_server.personal_campaign import PersonalCampaign
from provider_browser_smoke import NeverRun, counters
from test_providers import ProviderTests


def main():
    suffix = sys.argv[1] if len(sys.argv) == 2 and sys.argv[1] in ("01", "02", "03", "04") else "04"
    result = ROOT / (".artifacts/browser/dev-10/REGISTRATION-BROWSER-RESULT-" + suffix + ".json")
    if result.exists():
        raise SystemExit("one-use DEV-10 browser result already exists")
    fixture_test = ProviderTests("test_distinct_native_tls_inventory_and_readiness")
    fixture_test.setUp()
    server = None
    try:
        registry, store = fixture_test.registry, fixture_test.store
        registry.controlled_provider_proof = True
        registry.personal_campaign = PersonalCampaign(store, registry)
        registry.mutate("owner.local", {"operation_id": "op.dev10.browser.setup",
            "action": "create_connection", "subject": "conn.dev10-personal", "expected_revision": 0,
            "data": {"display_name": "Larry — Personal Duranki Testing",
                "adapter_id": "openai.responses.v1", "settings": fixture_test.settings(),
                "owner": "owner.local", "funding_kind": "personal_testing"}})
        fixture = json.loads((ROOT / "tests/gateway_integration/dev05_fixture.json").read_text())
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = serve("127.0.0.1", port, projection=OperatorProjection(store, "svc.demo"),
            runner=NeverRun(), password="p" * 40, fixture=fixture,
            build={"commit": "dev10-disposable-registration"}, web_root=ROOT / "web",
            worker_probe=lambda: {"state": "live"}, sender_status=lambda: {"state": "live"},
            registry=registry)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        before = counters(store)
        with tempfile.TemporaryDirectory(prefix="duranki-dev10-browser-") as scratch:
            run = Path(scratch)
            with HeadlessChrome(run, f"http://127.0.0.1:{port}/") as browser:
                wait_initial_page(browser)
                browser.evaluate(HELPERS)
                browser.evaluate("window.confirm=()=>true;document.querySelector('#password').value='"+
                    "p" * 40+"';document.querySelector('#login-form').requestSubmit();true")
                wait(browser, "!document.querySelector('#workspace').hidden", "workspace")
                browser.evaluate("location.hash='#/providers/openai/connections/conn.dev10-personal';true")
                wait(browser, "document.querySelector('#view-content').textContent.includes('Personal testing · finite allowance')",
                     "personal API setup")
                if len(fixture_test.server.requests):
                    raise RuntimeError("draft setup contacted provider")
                call(browser, "click", "Set up API access")
                call(browser, "fill", "secret", "discarded-synthetic-key-123456")
                call(browser, "click", "Cancel")
                wait(browser, "document.querySelector('#view-content').textContent.includes('Not set up')", "cancelled key")
                if registry.connection("conn.dev10-personal")["credential_state"] != "absent":
                    raise RuntimeError("cancel saved key")
                call(browser, "click", "Set up API access")
                call(browser, "submit", {"secret": "distinctive-synthetic-key-123456"})
                wait(browser, "document.querySelector('#view-content').textContent.includes('Key saved—not checked')",
                     "saved unchecked")
                if len(fixture_test.server.requests):
                    raise RuntimeError("Save contacted provider")
                if browser.evaluate("document.body.textContent.includes('distinctive-synthetic-key-123456')"):
                    raise RuntimeError("key leaked to rendered page")
                shot = screenshot(browser, run, "personal-api-setup-key-saved")
                call(browser, "click", "Test API access")
                wait(browser, "document.querySelector('#view-content').textContent.includes('API access verified')",
                     "explicit controlled access check")
                if len(fixture_test.server.requests) != 1:
                    raise RuntimeError("expected exactly one controlled access GET")
                call(browser, "click", "Discover models")
                deadline = time.monotonic() + 10
                while len(fixture_test.server.requests) < 2 and time.monotonic() < deadline:
                    time.sleep(0.05)
                if len(fixture_test.server.requests) != 2:
                    raise RuntimeError("expected exactly two controlled listing GETs")
                call(browser, "click", "Replace key")
                call(browser, "submit", {"secret": "replacement-synthetic-key-123456"})
                wait(browser, "document.querySelector('#view-content').textContent.includes('Key saved—not checked')",
                     "rotation invalidated check")
                call(browser, "click", "Remove key")
                wait(browser, "document.querySelector('#view-content').textContent.includes('Not set up')",
                     "removed key")
                if browser.evaluate("document.body.scrollWidth>window.innerWidth+1"):
                    raise RuntimeError("API setup controls overflow viewport")
                browser.evaluate("document.querySelector('#logout').click();true")
                wait(browser, "!document.querySelector('#login-view').hidden", "signed out")
            after = counters(store)
            if before != after:
                raise RuntimeError("provider registration launched model work")
            dump = " ".join(store.db.iterdump())
            if any(marker in dump for marker in ("distinctive-synthetic-key-123456",
                                            "replacement-synthetic-key-123456")):
                raise RuntimeError("plaintext key reached SQLite metadata")
            result.parent.mkdir(parents=True, exist_ok=True)
            target = result.parent / "screenshots" / ("dev10-personal-api-setup-key-saved-" + suffix + ".png")
            target.parent.mkdir(exist_ok=True)
            shutil.copy2(run / shot["file"], target)
            output = {"status": "PASS", "source_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(), "source_dirty": True,
                "scope": "disposable Chrome, SQLite and independent controlled loopback TLS",
                "provider_requests": [path for path, _ in fixture_test.server.requests],
                "generation_counts_before_after": {"before": before, "after": after},
                "credential_states": ["Not set up", "Key saved—not checked", "API access verified",
                                      "Key saved—not checked after rotation", "Not set up after removal"],
                "screenshot": {"path": str(target.relative_to(ROOT)), "sha256": shot["sha256"]},
                "source_hashes": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                    for name in ("web/providers_view.js", "web/source_pages.js", "web/crud_view.js",
                                 "server/src/duranki_server/personal_campaign.py")}}
            result.write_text(json.dumps(output, indent=2, sort_keys=True)+"\n")
            print(json.dumps(output, sort_keys=True))
    finally:
        if server:
            server.shutdown()
            server.server_close()
            server.operator_jobs.shutdown(wait=True)
        fixture_test.doCleanups()


if __name__ == "__main__":
    main()
