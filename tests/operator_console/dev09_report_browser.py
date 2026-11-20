#!/usr/bin/env python3
"""One-use actual Chrome report check against disposable synthetic accounting data."""

from __future__ import annotations

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
from ezllmrouter_server.operator_projection import OperatorProjection
from ezllmrouter_server.operator_web import serve
from provider_browser_smoke import NeverRun, counters
from test_dev09_reporting import ReportingTests


def main():
    suffix = sys.argv[1] if len(sys.argv) == 2 and sys.argv[1] in ("01", "02", "03", "04") else "01"
    destination = ROOT / (".artifacts/browser/dev-09/REPORT-BROWSER-RESULT-" + suffix + ".json")
    if destination.exists():
        raise SystemExit("DEV-09 report browser result already exists; preserve it")
    test = ReportingTests("test_fixture_conservation_replacement_and_cohorts")
    test.setUp()
    server = None
    try:
        store, registry = test.store, test.registry
        before = counters(store)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        fixture = json.loads((ROOT / "tests/gateway_integration/dev05_fixture.json").read_text())
        server = serve(
            "127.0.0.1",
            port,
            projection=OperatorProjection(store, "svc.demo"),
            runner=NeverRun(),
            password="p" * 40,
            fixture=fixture,
            build={"commit": "dev09-report-disposable", "dirty": True},
            web_root=ROOT / "web",
            worker_probe=lambda: {"state": "live"},
            sender_status=lambda: {"state": "live"},
            registry=registry,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        with tempfile.TemporaryDirectory(prefix="ezllmrouter-dev09-report-") as scratch:
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
                call(browser, "navigate", "usage")
                wait(
                    browser,
                    "document.querySelector('#view-title').textContent==='Usage & Costs' && "
                    "document.querySelector('#view-content').textContent.includes('Recorded through EzLLMRouter')",
                    "usage landing",
                )
                browser.evaluate("document.querySelector('.cost-filters summary').click();true")
                browser.evaluate(
                    "[...document.querySelectorAll('.cost-filter-grid label')]"
                    ".find(x=>x.textContent.includes('Revision cutoff')).querySelector('input').value="
                    "'2030-01-01T00:00:20Z';true"
                )
                call(browser, "click", "Apply filters")
                wait(
                    browser,
                    "document.querySelector('#view-content').textContent.includes('USD 32')",
                    "reconciled subtotal",
                )
                if (
                    browser.evaluate("document.querySelectorAll('.cost-bars .cost-bar-row').length")
                    < 2
                ):
                    raise RuntimeError("report bars were not drawn")
                browser.evaluate(
                    "[...document.querySelectorAll('#view-content h2')]"
                    ".find(x=>x.textContent.includes('Known cost over time')).scrollIntoView();true"
                )
                overview = screenshot(browser, run, "usage-costs-overview")
                browser.evaluate("document.querySelector('#view-content button').focus();true")
                browser.call(
                    "Input.dispatchKeyEvent",
                    {"type": "keyDown", "key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9},
                )
                browser.call(
                    "Input.dispatchKeyEvent",
                    {"type": "keyUp", "key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9},
                )
                if not browser.evaluate("document.activeElement.tagName==='BUTTON'"):
                    raise RuntimeError("report tabs were not keyboard reachable")
                call(browser, "click", "Agents")
                wait(
                    browser,
                    "document.querySelector('#view-content').textContent.includes('agent.idle')",
                    "all-agent inventory",
                )
                if not browser.evaluate(
                    "document.querySelector('#view-content').textContent.includes('Not instrumented')"
                ):
                    raise RuntimeError("instrumentation state missing")
                browser.evaluate(
                    "[...document.querySelectorAll('#view-content h2')]"
                    ".find(x=>x.textContent.includes('All registered agents')).scrollIntoView();true"
                )
                agents = screenshot(browser, run, "all-agent-report")
                if suffix == "04":
                    call(
                        browser,
                        "submit",
                        {
                            "agent_id": "agent.disposable.dev09",
                            "display_name": "Disposable synthetic agent",
                            "owner": "team.fixture",
                            "versions": "v1, v2",
                        },
                    )
                    wait(
                        browser,
                        "document.querySelector('#view-content').textContent.includes('agent.disposable.dev09')",
                        "agent registration",
                    )
                    browser.evaluate(
                        "window.confirm=()=>true;"
                        "[...document.querySelectorAll('#view-content tr')]"
                        ".find(x=>x.textContent.includes('agent.disposable.dev09'))"
                        ".querySelector('button.primary-link').click();true"
                    )
                    wait(
                        browser,
                        "document.querySelector('#view-content').textContent.includes('Identity and version')",
                        "new agent detail",
                    )
                    call(browser, "click", "Archive agent…")
                    wait(
                        browser,
                        "[...document.querySelectorAll('#view-content tr')]"
                        ".some(x=>x.textContent.includes('agent.disposable.dev09')&&x.textContent.includes('Archived'))",
                        "agent archived",
                    )
                    browser.evaluate(
                        "[...document.querySelectorAll('#view-content tr')]"
                        ".find(x=>x.textContent.includes('agent.disposable.dev09'))"
                        ".querySelector('button.primary-link').click();true"
                    )
                    wait(
                        browser,
                        "[...document.querySelectorAll('#view-content button')]"
                        ".some(x=>x.textContent.trim()==='Restore agent')",
                        "archived agent detail",
                    )
                    call(browser, "click", "Restore agent")
                    wait(
                        browser,
                        "[...document.querySelectorAll('#view-content tr')]"
                        ".some(x=>x.textContent.includes('agent.disposable.dev09')&&x.textContent.includes('Active'))",
                        "agent restored",
                    )
                browser.evaluate(
                    "[...document.querySelectorAll('#view-content tr')]"
                    ".find(x=>x.textContent.includes('agent.coordinator'))"
                    ".querySelector('button.primary-link').click();true"
                )
                wait(
                    browser,
                    "document.querySelector('#view-content').textContent.includes('Identity and version')",
                    "agent detail",
                )
                call(browser, "click", "Tasks & workflows")
                wait(
                    browser,
                    "document.querySelector('#view-content').textContent.includes('27')",
                    "cohort cost and accepted task",
                )
                browser.evaluate(
                    "[...document.querySelectorAll('#view-content h2')]"
                    ".find(x=>x.textContent.includes('Task cohort performance')).scrollIntoView();true"
                )
                tasks = screenshot(browser, run, "task-cohorts")
                if suffix == "04":
                    browser.evaluate("sourceGo('#/providers/openai');true")
                    wait(
                        browser,
                        "document.querySelector('#view-content').textContent.includes('Usage & Costs · openai')",
                        "provider scoped cost panel",
                    )
                    call(browser, "click", "Open filtered Usage & Costs")
                    wait(
                        browser,
                        "document.querySelector('#view-title').textContent==='Usage & Costs'&&"
                        "document.querySelector('#view-content').textContent.includes('0/0')",
                        "provider scoped report",
                    )
                exported = browser.evaluate(
                    "Promise.all(['csv','json'].map(async format=>{"
                    "const r=await fetch('/operator/v1/usage-costs?cutoff=2030-01-01T00%3A00%3A20Z&export='+format);"
                    "return {format,status:r.status,contentType:r.headers.get('content-type'),body:await r.text()};}))"
                )
                if len(exported) != 2 or any(row["status"] != 200 for row in exported):
                    raise RuntimeError("authorized exports failed")
                csv_body = next(row["body"] for row in exported if row["format"] == "csv")
                json_body = next(row["body"] for row in exported if row["format"] == "json")
                if len(csv_body.splitlines()) != 11 or json.loads(json_body)["total"][
                    "known_subtotals"
                ] != {"EUR": "4", "USD": "32"}:
                    raise RuntimeError("report and export did not reconcile")
                browser.evaluate("document.querySelector('#logout').click();true")
                wait(browser, "!document.querySelector('#login-view').hidden", "sign out")
            after = counters(store)
            if before != after:
                raise RuntimeError("report browsing added model traffic")
            screenshots = []
            for shot in (overview, agents, tasks):
                target = (
                    destination.parent / "screenshots" / ("dev09-" + suffix + "-" + shot["file"])
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    raise RuntimeError("screenshot already exists: " + str(target))
                shutil.copy2(run / shot["file"], target)
                screenshots.append(
                    {"path": str(target.relative_to(ROOT)), "sha256": shot["sha256"]}
                )
            record = {
                "status": "PASS",
                "source_commit": __import__("subprocess")
                .check_output(["git", "rev-parse", "HEAD"], cwd=ROOT)
                .decode()
                .strip(),
                "source_dirty": True,
                "scope": "disposable Chrome, synthetic arithmetic fixture and local SQLite",
                "known_subtotals": {"EUR": "4", "USD": "32"},
                "attempts": 10,
                "exports": ["CSV", "JSON"],
                "keyboard_tab": True,
                "signed_out": True,
                "traffic_before_after": {"before": before, "after": after},
                "screenshots": screenshots,
            }
            destination.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
            print(json.dumps(record, sort_keys=True))
    finally:
        if server:
            server.shutdown()
            server.server_close()
            server.operator_jobs.shutdown(wait=True)
            thread.join(timeout=3)
        test.doCleanups()


if __name__ == "__main__":
    main()
