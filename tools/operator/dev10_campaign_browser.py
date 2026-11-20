#!/usr/bin/env python3
"""Disposable normal-console allowance controls; no generation or provider traffic."""

from __future__ import annotations

if not __package__:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[2]
for relative in (
    "server/src",
    "deploy/local",
    "tests/gateway_integration",
    "tests/development_slice",
    "tests/operator_console",
):
    sys.path.insert(0, str(ROOT / relative))

from deploy.local.browser_cdp import HeadlessChrome
from deploy.local.crud_browser import HELPERS, call, wait, wait_initial_page, screenshot
from tools.gateway.evidence.dev08_integrated import prepare_registry
from ezllmrouter_server.operator_projection import OperatorProjection
from ezllmrouter_server.operator_web import serve
from ezllmrouter_server.personal_campaign import PersonalCampaign
from tools.operator.provider_browser_smoke import NeverRun, counters
from tests.operator_console.test_providers import ProviderTests


def main():
    suffix = (
        sys.argv[1]
        if len(sys.argv) == 2 and sys.argv[1] in ("01", "02", "03", "04", "05", "06")
        else "06"
    )
    result = ROOT / (".artifacts/browser/dev-10/CAMPAIGN-BROWSER-RESULT-" + suffix + ".json")
    if result.exists():
        raise SystemExit("one-use DEV-10 browser result already exists")
    with tempfile.TemporaryDirectory(prefix="ezllmrouter-dev10-campaign-") as scratch:
        run = Path(scratch)
        fixture_tls = ProviderTests("test_distinct_native_tls_inventory_and_readiness")
        fixture_tls.setUp()
        fixture = json.loads((ROOT / "tools/gateway/evidence/dev05_fixture.json").read_text())
        store, authority, registry, model = prepare_registry(
            run,
            fixture,
            fixture_tls.origin,
            fixture_tls.cert,
            funding_kind="personal_testing",
            display_name="Larry — Personal EzLLMRouter Testing",
        )
        server = None
        try:
            registry.mutate(
                "owner.local",
                {
                    "operation_id": "op.dev10.browser.owner.grant",
                    "action": "set_grant",
                    "subject": "owner.local",
                    "expected_revision": 0,
                    "data": {
                        "configuration_ref": model["configuration_ref"],
                        "status": "active",
                        "purposes": ["execution"],
                        "task_classes": ["class.demo"],
                    },
                },
            )
            registry.personal_campaign = PersonalCampaign(store, registry)
            registry.probe_connection(
                "owner.local", "conn.dev08-controlled", 4, "op.dev10.browser.access", "access"
            )
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
                build={"commit": "dev10-disposable-campaign"},
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
                browser.evaluate(
                    "location.hash='#/providers/openai/connections/conn.dev08-controlled';true"
                )
                wait(
                    browser,
                    "document.querySelector('#view-content').textContent.includes('Personal testing · finite allowance')",
                    "personal campaign panel",
                )
                call(browser, "click", "Configure allowance")
                expiry = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
                call(
                    browser,
                    "submit",
                    {
                        "configuration_ref": model["configuration_ref"],
                        "currency": "USD",
                        "allowance_decimal": "0.02",
                        "per_request_decimal": "0.01",
                        "max_requests": "1",
                        "max_input_bytes": "4096",
                        "max_output_tokens": "32",
                        "expires_at": expiry,
                    },
                )
                wait(
                    browser,
                    "document.querySelector('#view-content').textContent.includes('Activate allowance')",
                    "disabled draft",
                )
                if registry.personal_campaign.summary()["state"] != "draft":
                    raise RuntimeError("campaign auto-activated")
                call(browser, "click", "Activate allowance")
                wait(
                    browser,
                    "document.querySelector('#view-content').textContent.includes('Run one live test')",
                    "active allowance controls",
                )
                browser.call(
                    "Emulation.setDeviceMetricsOverride",
                    {"width": 1440, "height": 1600, "deviceScaleFactor": 1, "mobile": False},
                )
                shot = screenshot(browser, run, "personal-allowance-active-no-send")
                if browser.evaluate("document.body.scrollWidth>window.innerWidth+1"):
                    raise RuntimeError("campaign controls overflow viewport")
                call(browser, "click", "Pause allowance")
                wait(
                    browser,
                    "document.querySelector('#view-content').textContent.includes('Activate allowance')",
                    "paused allowance",
                )
                browser.evaluate("document.querySelector('#logout').click();true")
                wait(browser, "!document.querySelector('#login-view').hidden", "signed out")
            after = counters(store)
            if before != after:
                raise RuntimeError("allowance browser created model traffic")
            target = (
                result.parent
                / "screenshots"
                / ("dev10-personal-allowance-active-no-send-" + suffix + ".png")
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(run / shot["file"], target)
            payload = {
                "status": "PASS",
                "scope": "disposable Chrome, persistent SQLite and controlled loopback TLS",
                "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT)
                .decode()
                .strip(),
                "source_dirty": True,
                "controls": [
                    "Configure allowance",
                    "Activate allowance",
                    "Run one live test shown but not invoked",
                    "Pause allowance",
                    "Close allowance",
                ],
                "final_state": registry.personal_campaign.summary()["state"],
                "generation_counts_before_after": {"before": before, "after": after},
                "controlled_management_requests": [path for path, _ in fixture_tls.server.requests],
                "screenshot": {"path": str(target.relative_to(ROOT)), "sha256": shot["sha256"]},
                "source_hashes": {
                    name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                    for name in (
                        "web/source_pages.js",
                        "server/src/ezllmrouter_server/personal_campaign.py",
                    )
                },
            }
            result.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            print(json.dumps(payload, sort_keys=True))
        finally:
            if server:
                server.shutdown()
                server.server_close()
                server.operator_jobs.shutdown(wait=True)
            store.close()
            fixture_tls.doCleanups()


if __name__ == "__main__":
    main()
