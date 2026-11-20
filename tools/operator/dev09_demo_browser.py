#!/usr/bin/env python3
"""One-use Chrome proof of the isolated, scripted DEV-09 workspace."""

from __future__ import annotations

if not __package__:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import csv
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
for relative in ("server/src", "deploy/local", "tests/operator_console"):
    sys.path.insert(0, str(ROOT / relative))

from deploy.local.browser_cdp import HeadlessChrome
from deploy.local.crud_browser import HELPERS, call, wait, wait_initial_page, screenshot
from ezllmrouter_server.operator_projection import OperatorProjection
from ezllmrouter_server.operator_web import serve
from tests.operator_console.test_reporting import ReportingTests


class NeverRun:
    def run(self, *_):
        raise AssertionError("scripted playback must not launch model work")


def counters(store):
    return {
        name: store.db.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
        for name in ("submissions", "intents", "guard_dispatches")
    }


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    suffix = sys.argv[1] if len(sys.argv) == 2 and sys.argv[1] in ("01", "02", "03") else "01"
    destination = ROOT / (".artifacts/browser/dev-09/DEMO-BROWSER-RESULT-" + suffix + ".json")
    if destination.exists():
        raise SystemExit("demo browser result already exists; preserve one-use evidence")
    test = ReportingTests("test_fixture_conservation_replacement_and_cohorts")
    test.setUp()
    server = None
    try:
        store, registry = test.store, test.registry
        before = counters(store)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        fixture = json.loads((ROOT / "tools/gateway/evidence/dev05_fixture.json").read_text())
        server = serve(
            "127.0.0.1",
            port,
            projection=OperatorProjection(store, "svc.demo"),
            runner=NeverRun(),
            password="p" * 40,
            fixture=fixture,
            build={"commit": "dev09-demo-disposable", "dirty": True},
            web_root=ROOT / "web",
            worker_probe=lambda: {"state": "live"},
            sender_status=lambda: {"state": "live"},
            registry=registry,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        with tempfile.TemporaryDirectory(prefix="ezllmrouter-dev09-demo-") as scratch:
            run = Path(scratch)
            with HeadlessChrome(run, f"http://127.0.0.1:{port}/") as browser:
                wait_initial_page(browser)
                time.sleep(0.4)
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
                    "document.querySelector('#view-content').textContent.includes('Open demo workspace')",
                    "operational usage",
                )
                baseline = browser.evaluate(
                    "fetch('/operator/v1/usage-costs?cutoff=2030-01-01T00%3A00%3A20Z').then(r=>r.json())"
                )
                browser.evaluate(
                    "window.__demoRequests=[];const originalFetch=window.fetch;"
                    "window.fetch=(url,options={})=>{if(demoUi.open)window.__demoRequests.push({url:String(url),method:options.method||'GET'});"
                    "return originalFetch(url,options)};true"
                )
                call(browser, "click", "Open demo workspace")
                wait(
                    browser,
                    "document.querySelector('.demo-banner')&&"
                    "document.querySelector('.cards .value').textContent==='USD 0.32'",
                    "completed main demo",
                )
                check(
                    browser.evaluate(
                        "demoUi.data.identity==='dev09-scripted-cost-demo-v1'&&"
                        "demoSnapshot().total.attempts===6"
                    ),
                    "main cost or identity",
                )
                check(
                    browser.evaluate(
                        "document.querySelectorAll('.demo-lane').length===4&&"
                        "document.querySelector('.demo-banner').textContent.includes('simulated USD')"
                    ),
                    "timeline lanes or simulated label",
                )
                timeline = screenshot(browser, run, "timeline-main")
                browser.evaluate(
                    "[...document.querySelectorAll('#view-content h2')]"
                    ".find(x=>x.textContent.includes('Cumulative simulated cost')).scrollIntoView();true"
                )
                chart = screenshot(browser, run, "cost-step-main")
                browser.evaluate(
                    "(()=>{const slider=document.querySelector('.demo-controls input[type=range]');"
                    "slider.value='30';slider.dispatchEvent(new Event('input',{bubbles:true}));return true})()"
                )
                check(
                    browser.evaluate(
                        "demoSnapshot().total.known_subtotals.USD==='0.19'&&"
                        "demoSnapshot().total.attempts===3&&"
                        "document.querySelector('.cards .value').textContent==='USD 0.19'"
                    ),
                    "30-second cutoff",
                )
                browser.evaluate(
                    "[...document.querySelectorAll('.demo-marker')]"
                    ".find(x=>x.title.includes('Newton requests')).focus();true"
                )
                browser.call(
                    "Input.dispatchKeyEvent",
                    {
                        "type": "rawKeyDown",
                        "key": "Enter",
                        "code": "Enter",
                        "windowsVirtualKeyCode": 13,
                        "nativeVirtualKeyCode": 13,
                    },
                )
                browser.call(
                    "Input.dispatchKeyEvent",
                    {
                        "type": "char",
                        "key": "Enter",
                        "code": "Enter",
                        "text": "\r",
                        "windowsVirtualKeyCode": 13,
                    },
                )
                browser.call(
                    "Input.dispatchKeyEvent",
                    {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13},
                )
                keyboard_state = browser.evaluate(
                    "({selected:demoUi.selected,active:document.activeElement?.getAttribute('aria-label'),"
                    "details:[...document.querySelectorAll('#view-content .panel')]"
                    ".find(x=>x.querySelector('h2')?.textContent.includes('Selected event'))?.textContent})"
                )
                check(
                    browser.evaluate(
                        "demoUi.selected==='demo.event.review.done'&&"
                        "[...document.querySelectorAll('#view-content .panel')]"
                        ".find(x=>x.querySelector('h2')?.textContent.includes('Selected event'))"
                        ".textContent.includes('USD 0.04')"
                    ),
                    "keyboard drill-down: " + str(keyboard_state),
                )
                call(browser, "click", "Reset to start")
                check(
                    browser.evaluate("demoUi.time===0&&demoSnapshot().total.attempts===0"), "reset"
                )
                call(browser, "click", "Play")
                wait(browser, "demoUi.time>0", "play advance")
                call(browser, "click", "Pause")
                paused = browser.evaluate("demoUi.time")
                browser.evaluate("new Promise(resolve=>setTimeout(resolve,650))")
                check(browser.evaluate("demoUi.time") == paused, "pause changed cutoff")
                call(browser, "click", "Restart replay")
                wait(browser, "demoUi.time>0", "restart advance")
                call(browser, "click", "Pause")
                browser.evaluate(
                    "(()=>{const slider=document.querySelector('.demo-controls input[type=range]');"
                    "slider.value=slider.max;slider.dispatchEvent(new Event('input',{bubbles:true}));return true})()"
                )
                check(
                    browser.evaluate(
                        "demoUi.time===90&&demoSnapshot().total.known_subtotals.USD==='0.32'"
                    ),
                    "repeat completion",
                )
                selector_state = browser.evaluate(
                    "({count:document.querySelectorAll('.demo-selectors select').length,"
                    "html:document.querySelector('.demo-selectors')?.outerHTML,"
                    "message:document.querySelector('#view-message')?.textContent})"
                )
                check(
                    selector_state["count"] == 3, "demo selectors missing: " + str(selector_state)
                )
                actor_change = browser.evaluate(
                    "(()=>{const selects=document.querySelectorAll('.demo-selectors select');"
                    "const actor=selects[1];if(!actor)return {count:selects.length,html:document.querySelector('.demo-selectors')?.outerHTML,"
                    "message:document.querySelector('#view-message')?.textContent};"
                    "actor.value='demo.agent.patton';actor.dispatchEvent(new Event('change',{bubbles:true}));return true})()"
                )
                check(actor_change is True, "actor selector disappeared: " + str(actor_change))
                wait(
                    browser,
                    "demoSnapshot().total.known_subtotals.USD==='0.11'&&"
                    "document.querySelectorAll('.demo-selectors select').length===3",
                    "actor filter",
                )
                browser.evaluate(
                    "(()=>{const provider=document.querySelectorAll('.demo-selectors select')[2];"
                    "provider.value='demo.provider.beacon';provider.dispatchEvent(new Event('change',{bubbles:true}));return true})()"
                )
                wait(
                    browser,
                    "demoSnapshot().total.attempts===0&&"
                    "document.querySelectorAll('.demo-selectors select').length===3",
                    "empty intersection",
                )
                empty_state = browser.evaluate(
                    "({count:document.querySelectorAll('.demo-selectors select').length,"
                    "message:document.querySelector('#view-message')?.textContent,"
                    "view:document.querySelector('#view-content')?.textContent.slice(0,250)})"
                )
                check(
                    empty_state["count"] == 3,
                    "empty intersection did not render: " + str(empty_state),
                )
                browser.evaluate(
                    "(()=>{const actor=document.querySelectorAll('.demo-selectors select')[1];"
                    "actor.value='';actor.dispatchEvent(new Event('change',{bubbles:true}));return true})()"
                )
                wait(
                    browser,
                    "demoSnapshot().total.known_subtotals.USD==='0.17'&&"
                    "document.querySelectorAll('.demo-selectors select').length===3",
                    "provider filter",
                )
                browser.evaluate(
                    "(()=>{const provider=document.querySelectorAll('.demo-selectors select')[2];"
                    "provider.value='';provider.dispatchEvent(new Event('change',{bubbles:true}));return true})()"
                )
                wait(
                    browser,
                    "demoSnapshot().total.known_subtotals.USD==='0.32'&&"
                    "document.querySelectorAll('.demo-selectors select').length===3",
                    "clear filter",
                )
                browser.evaluate(
                    "(()=>{const story=document.querySelectorAll('.demo-selectors select')[0];"
                    "story.value='all';story.dispatchEvent(new Event('change',{bubbles:true}));return true})()"
                )
                wait(
                    browser,
                    "demoSnapshot().total.known_subtotals.USD==='0.46'&&"
                    "document.querySelectorAll('.demo-selectors select').length===3",
                    "all stories",
                )
                check(
                    browser.evaluate(
                        "demoSnapshot().total.attempts===9&&"
                        "document.querySelector('.cards .value').textContent==='USD 0.46'"
                    ),
                    "all story card",
                )
                browser.evaluate("window.scrollTo(0,0);true")
                all_stories = screenshot(browser, run, "all-stories")
                browser.evaluate(
                    "window.__demoExports=[];URL.createObjectURL=blob=>{"
                    "window.__demoExports.push(blob.text());return 'blob:demo-capture'};"
                    "HTMLAnchorElement.prototype.click=function(){return true};true"
                )
                call(browser, "click", "Export demo JSON")
                call(browser, "click", "Export demo CSV")
                exports = browser.evaluate("Promise.all(window.__demoExports)")
                check(len(exports) == 2, "missing exports")
                exported = json.loads(exports[0])
                check(
                    exported["total"]["known_subtotals"] == {"USD": "0.46"}
                    and len(exported["attempts"]) == 9
                    and exported["fixture"] == "dev09-scripted-cost-demo-v1",
                    "JSON export mismatch",
                )
                csv_rows = list(csv.DictReader(io.StringIO(exports[1])))
                check(
                    len(csv_rows) == 9
                    and sum((Decimal(row["amount_decimal"]) for row in csv_rows), Decimal(0))
                    == Decimal("0.46")
                    and all(row["fixture"] == exported["fixture"] for row in csv_rows),
                    "CSV export mismatch",
                )
                requests = browser.evaluate("window.__demoRequests")
                check(bool(requests), "demo request capture was empty")
                check(
                    all(
                        row["method"] == "GET"
                        and row["url"].startswith("/operator/v1/demo-workspace?")
                        for row in requests
                    ),
                    "demo made a non-demo or mutating request",
                )
                check(len(requests) <= 8, "replay caused another server request")
                call(browser, "click", "Return to operational Usage & Costs")
                wait(
                    browser,
                    "document.querySelector('#view-content').textContent.includes('Open demo workspace')",
                    "operational return",
                )
                after_report = browser.evaluate(
                    "fetch('/operator/v1/usage-costs?cutoff=2030-01-01T00%3A00%3A20Z').then(r=>r.json())"
                )
                check(
                    baseline["total"] == after_report["total"]
                    and baseline["attempts"] == after_report["attempts"],
                    "operational report changed",
                )
            after = counters(store)
            check(before == after, "demo changed durable model traffic counters")
            screenshots = []
            for shot in (timeline, chart, all_stories):
                target = (
                    destination.parent
                    / "screenshots"
                    / ("dev09-demo-" + suffix + "-" + shot["file"])
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    raise RuntimeError("screenshot already exists: " + str(target))
                shutil.copy2(run / shot["file"], target)
                screenshots.append(
                    {"path": str(target.relative_to(ROOT)), "sha256": shot["sha256"]}
                )
            hashes = {
                name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                for name in (
                    "web/dev09_demo_fixture.json",
                    "web/demo_workspace_view.js",
                    "web/app.css",
                    "web/usage_costs_view.js",
                    "server/src/ezllmrouter_server/demo_workspace.py",
                    "server/src/ezllmrouter_server/operator_web.py",
                )
            }
            record = {
                "status": "PASS",
                "identity": "dev09-scripted-cost-demo-v1",
                "scope": "disposable authenticated Chrome, temporary SQLite, fictional fixed fixture",
                "main_usd": "0.32",
                "all_stories_usd": "0.46",
                "attempts": 9,
                "checks": [
                    "timeline",
                    "step chart",
                    "30-second cutoff",
                    "keyboard drill-down",
                    "play",
                    "pause",
                    "restart",
                    "seek",
                    "actor/provider filters",
                    "JSON/CSV exports",
                    "return to operational report",
                    "no POST or provider request",
                    "stable durable counters",
                ],
                "requests_during_demo": requests,
                "traffic_before_after": {"before": before, "after": after},
                "source_sha256": hashes,
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
