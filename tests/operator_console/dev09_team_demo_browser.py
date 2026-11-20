#!/usr/bin/env python3
"""One-use disposable Chrome evidence for the versioned DEV-09 team demo."""

from __future__ import annotations

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

from browser_cdp import HeadlessChrome
from crud_browser import HELPERS, call, wait, wait_initial_page, screenshot
from ezllmrouter_server.operator_projection import OperatorProjection
from ezllmrouter_server.operator_web import serve
from test_dev09_reporting import ReportingTests


class NeverRun:
    def run(self, *_):
        raise AssertionError("team demo must not launch model work")


def counters(store):
    return {
        name: store.db.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
        for name in ("submissions", "intents", "guard_dispatches")
    }


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def choose(browser, label, value):
    expression = (
        "(()=>{const input=[...document.querySelectorAll('.demo-selectors label')]"
        + ".find(x=>x.textContent.startsWith("
        + json.dumps(label)
        + "))?.querySelector('select');"
        + "if(!input)throw Error('missing selector');input.value="
        + json.dumps(value)
        + ";input.dispatchEvent(new Event('change',{bubbles:true}));return true})()"
    )
    browser.evaluate(expression)
    wait(
        browser,
        "document.querySelectorAll('.demo-selectors select').length===5&&"
        "document.querySelector('#view-message').textContent===''&&"
        "demoUi.data?.collection===demoUi.collection&&demoUi.data?.selected_story===demoUi.story&&"
        "demoUi.data?.selected_actor===demoUi.actor&&demoUi.data?.selected_person===demoUi.person&&"
        "demoUi.data?.selected_provider===demoUi.provider",
        "rendered " + label,
    )


def main():
    destination = ROOT / ".artifacts/browser/dev-09/TEAM-DEMO-BROWSER-RESULT-04.json"
    if destination.exists():
        raise SystemExit("team browser result exists; preserve one-use evidence")
    fixture_test = ReportingTests("test_fixture_conservation_replacement_and_cohorts")
    fixture_test.setUp()
    server = None
    try:
        store, registry = fixture_test.store, fixture_test.registry
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
            build={"commit": "dev09-team-disposable", "dirty": True},
            web_root=ROOT / "web",
            worker_probe=lambda: {"state": "not configured"},
            sender_status=lambda: {"state": "not configured"},
            registry=registry,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        with tempfile.TemporaryDirectory(prefix="ezllmrouter-dev09-team-") as scratch:
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
                    "window.__teamRequests=[];const teamFetch=window.fetch;"
                    "window.fetch=(url,options={})=>{if(demoUi.open)window.__teamRequests.push({url:String(url),method:options.method||'GET'});"
                    "return teamFetch(url,options)};true"
                )
                call(browser, "click", "Open demo workspace")
                wait(
                    browser,
                    "demoUi.data?.identity==='dev09-team-scripted-cost-demo-v2'&&"
                    "document.querySelector('.demo-cards .value')?.textContent==='USD 0.39'",
                    "Oren focus",
                )
                check(
                    browser.evaluate(
                        "demoSnapshot().total.attempts===8&&"
                        "document.querySelectorAll('.demo-lane').length>=8&&"
                        "document.querySelector('.demo-banner').textContent.includes('simulated USD')"
                    ),
                    "focused workflow or label",
                )
                desktop_layout = browser.evaluate(
                    "(()=>{const t=document.querySelector('.demo-viz .panel').getBoundingClientRect();"
                    "const c=document.querySelector('.demo-viz .panel:has(svg)').getBoundingClientRect();"
                    "return {timelineTop:t.top,timelineBottom:t.bottom,chartTop:c.top,chartBottom:c.bottom,"
                    "viewport:innerHeight,width:innerWidth,overflow:document.documentElement.scrollWidth-innerWidth}})()"
                )
                check(
                    desktop_layout["chartTop"] >= desktop_layout["timelineBottom"]
                    and desktop_layout["chartBottom"] <= desktop_layout["viewport"] + 10
                    and desktop_layout["overflow"] <= 1,
                    "desktop timeline/chart layout: " + str(desktop_layout),
                )
                focus_shot = screenshot(browser, run, "oren-focused-timeline-cost")
                browser.evaluate(
                    "[...document.querySelectorAll('.demo-call')]"
                    ".find(x=>x.title.includes('Vega')&&x.title.includes('Research')).focus();true"
                )
                check(
                    browser.evaluate(
                        "document.querySelector('#demo-inspector-body').textContent.includes('25 simulated seconds')&&"
                        "document.querySelector('#demo-inspector-body').textContent.includes('USD 0.12')"
                    ),
                    "keyboard focus inspector",
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
                check(
                    browser.evaluate(
                        "demoUi.time===42&&demoSnapshot().total.known_subtotals.USD==='0.23'"
                    ),
                    "keyboard selected delayed usage observation",
                )
                inspector_shot = screenshot(browser, run, "selected-vega-inspector")
                call(browser, "click", "Team activity")
                wait(
                    browser,
                    "demoUi.story==='team'&&demoSnapshot().total.known_subtotals.USD==='1.25'&&"
                    "document.querySelectorAll('.demo-workflow-group').length===6",
                    "team activity",
                )
                browser.evaluate(
                    "(()=>{const input=document.querySelector('.demo-controls input[type=range]');"
                    "input.value='65';input.dispatchEvent(new Event('input',{bubbles:true}));return true})()"
                )
                check(
                    browser.evaluate(
                        "demoSnapshot().total.known_subtotals.USD==='0.84'&&"
                        "demoSnapshot().total.attempts===16&&"
                        "demoUi.data.attempts.filter(x=>x.usage_at===65).length===3"
                    ),
                    "simultaneous step at 65 seconds",
                )
                team_layout = browser.evaluate(
                    "(()=>{const c=document.querySelector('.demo-viz .panel:has(svg)').getBoundingClientRect();"
                    "return {chartTop:c.top,chartBottom:c.bottom,viewport:innerHeight}})()"
                )
                check(
                    team_layout["chartBottom"] <= team_layout["viewport"] + 10,
                    "team timeline/chart layout: " + str(team_layout),
                )
                team_shot = screenshot(browser, run, "team-overlap-cost-65s")
                choose(browser, "Person", "demo.user.brant")
                choose(browser, "Agent", "demo.agent.patton")
                check(
                    browser.evaluate(
                        "demoSnapshot().total.known_subtotals.USD==='0.05'&&"
                        "demoSnapshot().attempts.every(x=>x.user==='demo.user.brant')&&"
                        "document.querySelectorAll('.demo-event.demo-context').length>0"
                    ),
                    "Brant/Patton filter",
                )
                choose(browser, "Person", "demo.user.andrew")
                check(
                    browser.evaluate(
                        "demoSnapshot().total.known_subtotals.USD==='0.04'&&"
                        "demoSnapshot().attempts.every(x=>x.root_run_id==='demo.run.andrew.patton')"
                    ),
                    "Andrew/Patton attribution",
                )
                choose(browser, "Agent", "")
                choose(browser, "Person", "")
                choose(browser, "Provider", "demo.provider.beacon")
                browser.evaluate(
                    "(()=>{const input=document.querySelector('.demo-controls input[type=range]');"
                    "input.value=input.max;input.dispatchEvent(new Event('input',{bubbles:true}));return true})()"
                )
                check(
                    browser.evaluate(
                        "demoSnapshot().total.known_subtotals.USD==='0.61'&&"
                        "demoSnapshot().attempts.every(x=>x.provider==='demo.provider.beacon')&&"
                        "document.querySelector('.demo-cards .label').textContent==='Filtered simulated cost'"
                    ),
                    "named provider filter",
                )
                choose(browser, "Provider", "")
                choose(browser, "Agent", "demo.agent.idle")
                check(
                    browser.evaluate(
                        "demoSnapshot().total.attempts===0&&"
                        "document.querySelector('.demo-empty-note').textContent.includes('No activity recorded')"
                    ),
                    "idle synthetic coverage",
                )
                choose(browser, "Agent", "demo.agent.uninstrumented")
                check(
                    browser.evaluate(
                        "demoSnapshot().total.attempts===0&&"
                        "document.querySelector('.demo-empty-note').textContent.includes('not measured')"
                    ),
                    "uninstrumented coverage",
                )
                choose(browser, "Agent", "")
                choose(browser, "Story", "andrew_direct")
                check(
                    browser.evaluate(
                        "demoSnapshot().total.known_subtotals.USD==='0.02'&&"
                        "demoSnapshot().attempts[0].agent_id===null"
                    ),
                    "direct human",
                )
                choose(browser, "Story", "scheduled_intelligence")
                check(
                    browser.evaluate(
                        "demoSnapshot().total.known_subtotals.USD==='0.1'&&"
                        "demoSnapshot().attempts.every(x=>x.user===null&&x.owner==='demo.team.mach33')"
                    ),
                    "scheduled owner",
                )
                choose(browser, "Collection", "legacy")
                wait(
                    browser,
                    "demoUi.collection==='legacy'&&demoUi.story==='main'",
                    "legacy collection",
                )
                choose(browser, "Story", "all")
                check(
                    browser.evaluate(
                        "demoSnapshot().total.known_subtotals.USD==='0.46'&&"
                        "demoSnapshot().total.attempts===9"
                    ),
                    "legacy reference",
                )
                choose(browser, "Collection", "expanded")
                wait(
                    browser,
                    "demoUi.story==='expanded_all'&&demoSnapshot().total.known_subtotals.USD==='1.39'",
                    "expanded collection",
                )
                check(
                    browser.evaluate("demoSnapshot().total.attempts===33"),
                    "expanded unique attempts",
                )
                default_expanded = browser.evaluate(
                    "fetch('/operator/v1/demo-workspace?collection=expanded').then(r=>r.json())"
                )
                check(
                    default_expanded["selected_story"] == "expanded_all"
                    and default_expanded["all_total"]["attempts"] == 33,
                    "expanded endpoint default",
                )
                browser.evaluate(
                    "window.__teamExports=[];URL.createObjectURL=blob=>{"
                    "window.__teamExports.push(blob.text());return 'blob:team-capture'};"
                    "HTMLAnchorElement.prototype.click=function(){return true};true"
                )
                call(browser, "click", "Export demo JSON")
                call(browser, "click", "Export demo CSV")
                exports = browser.evaluate("Promise.all(window.__teamExports)")
                check(len(exports) == 2, "missing exports")
                exported = json.loads(exports[0])
                rows = list(csv.DictReader(io.StringIO(exports[1])))
                check(
                    exported["fixture"] == "dev09-team-scripted-cost-demo-v2"
                    and exported["total"]["known_subtotals"] == {"USD": "1.39"}
                    and len(exported["attempts"]) == len(rows) == 33
                    and sum((Decimal(row["amount_decimal"]) for row in rows), Decimal(0))
                    == Decimal("1.39"),
                    "expanded exports",
                )
                call(browser, "click", "Reset to start")
                check(
                    browser.evaluate(
                        "demoUi.time===0&&!demoUi.playing&&demoSnapshot().total.attempts===0"
                    ),
                    "reset pauses at zero",
                )
                browser.evaluate(
                    "(()=>{const speed=[...document.querySelectorAll('.demo-controls label')]"
                    ".find(x=>x.textContent.startsWith('Speed')).querySelector('select');"
                    "speed.value='1';speed.dispatchEvent(new Event('change',{bubbles:true}));return true})()"
                )
                call(browser, "click", "Play")
                one_x = browser.evaluate(
                    "new Promise(resolve=>{const t=performance.now(),v=demoNow();"
                    "setTimeout(()=>resolve({delta:demoNow()-v,elapsed:(performance.now()-t)/1000}),1150)})"
                )
                check(
                    0.9 <= one_x["delta"] / one_x["elapsed"] <= 1.1,
                    "1× wall-time pace: " + str(one_x),
                )
                browser.evaluate(
                    "(()=>{const speed=[...document.querySelectorAll('.demo-controls label')]"
                    ".find(x=>x.textContent.startsWith('Speed')).querySelector('select');"
                    "speed.value='4';speed.dispatchEvent(new Event('change',{bubbles:true}));return true})()"
                )
                four_x = browser.evaluate(
                    "new Promise(resolve=>{const t=performance.now(),v=demoNow();"
                    "setTimeout(()=>resolve({delta:demoNow()-v,elapsed:(performance.now()-t)/1000}),700)})"
                )
                check(
                    3.6 <= four_x["delta"] / four_x["elapsed"] <= 4.4,
                    "4× wall-time pace: " + str(four_x),
                )
                call(browser, "click", "Pause")
                paused = browser.evaluate("demoUi.time")
                browser.evaluate("new Promise(resolve=>setTimeout(resolve,500))")
                check(browser.evaluate("demoUi.time") == paused, "pause moved cursor")
                browser.evaluate(
                    "(()=>{const input=document.querySelector('.demo-controls input[type=range]');"
                    "input.value=input.max;input.dispatchEvent(new Event('input',{bubbles:true}));return true})()"
                )
                call(browser, "click", "Replay")
                wait(browser, "demoUi.time>0&&demoUi.time<10", "replay from completion")
                call(browser, "click", "Reset to start")
                browser.call(
                    "Emulation.setDeviceMetricsOverride",
                    {"width": 900, "height": 900, "deviceScaleFactor": 1, "mobile": False},
                )
                choose(browser, "Collection", "team")
                choose(browser, "Story", "oren_opportunity")
                narrow = browser.evaluate(
                    "({width:innerWidth,overflow:document.documentElement.scrollWidth-innerWidth,"
                    "selectors:document.querySelectorAll('.demo-selectors select').length,"
                    "chart:!!document.querySelector('.demo-viz svg'),inspector:!!document.querySelector('#demo-inspector')})"
                )
                check(
                    narrow["width"] == 900
                    and narrow["overflow"] <= 1
                    and narrow["selectors"] == 5
                    and narrow["chart"]
                    and narrow["inspector"],
                    "narrow layout: " + str(narrow),
                )
                narrow_shot = screenshot(browser, run, "narrow-layout")
                requests = browser.evaluate("window.__teamRequests")
                check(
                    requests
                    and all(
                        row["method"] == "GET"
                        and row["url"].startswith("/operator/v1/demo-workspace?")
                        for row in requests
                    ),
                    "unexpected demo request",
                )
                call(browser, "click", "← Operational Usage & Costs")
                wait(
                    browser,
                    "document.querySelector('#view-content').textContent.includes('Open demo workspace')",
                    "return to operational",
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
            check(before == after, "demo changed durable counters")
            screenshots = []
            for shot in (focus_shot, inspector_shot, team_shot, narrow_shot):
                target = destination.parent / "screenshots" / ("dev09-team-04-" + shot["file"])
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    raise RuntimeError("screenshot exists: " + str(target))
                shutil.copy2(run / shot["file"], target)
                screenshots.append(
                    {"path": str(target.relative_to(ROOT)), "sha256": shot["sha256"]}
                )
            hashes = {
                name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                for name in (
                    "web/dev09_demo_fixture.json",
                    "web/dev09_team_demo_fixture.json",
                    "web/demo_workspace_team_view.js",
                    "web/app.css",
                    "server/src/ezllmrouter_server/demo_workspace_team.py",
                    "server/src/ezllmrouter_server/operator_web.py",
                )
            }
            record = {
                "status": "PASS",
                "fixture": "dev09-team-scripted-cost-demo-v2",
                "scope": "disposable authenticated Chrome, temporary SQLite, no model worker",
                "legacy_usd": "0.46",
                "team_usd": "1.25",
                "expanded_usd": "1.39",
                "expanded_attempts": 33,
                "desktop_layout": desktop_layout,
                "narrow_layout": narrow,
                "speed_observation_seconds": {"one_x": one_x, "four_x": four_x},
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
        fixture_test.doCleanups()


if __name__ == "__main__":
    main()
