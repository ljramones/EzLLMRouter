#!/usr/bin/env python3
"""One-use disposable Chrome proof of the DEV-09 shared-clock plot geometry."""

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
        raise AssertionError("alignment playback must not launch model work")


GEOMETRY = """(()=>{
  const rect=el=>{const r=el.getBoundingClientRect();return {left:r.left,right:r.right,width:r.width}};
  const center=el=>{const r=el.getBoundingClientRect();return r.left+r.width/2};
  const track=el=>{if(!el)return null;const r=el.getBoundingClientRect(),s=getComputedStyle(el);
    const left=r.left+parseFloat(s.borderLeftWidth),right=r.right-parseFloat(s.borderRightWidth);
    return {left,right,width:right-left,cursor:el.querySelector('.demo-track-cursor')?.getBoundingClientRect().left}};
  const group=name=>[...document.querySelectorAll('.demo-workflow-group')]
    .find(el=>el.querySelector('.demo-workflow-head strong')?.textContent.startsWith(name));
  const event='demo.event.oren.ask',oren=group('Oren'),summary=oren?.querySelector('.demo-track-summary'),
    participant=oren?.querySelector('.demo-lane:not(.demo-workflow-row) .demo-track'),
    svg=document.querySelector('.demo-viz svg'),axis=document.querySelector('.demo-ticks'),
    guide=svg.querySelector('.demo-selected-line'),chartCursor=svg.querySelector('line[stroke="#ffd887"]');
  const bars={};for(const [name,id] of Object.entries({
    brant:'demo.attempt.brant.boole.check.done',
    delivery:'demo.attempt.andrew.ironside.summary.done',
    direct:'demo.attempt.andrew.direct.done'})){
    const g=group(name==='brant'?'Brant':name==='delivery'?'Andrew · delivery':'Andrew · direct');
    bars[name]={summary:g?.querySelector('.demo-track-summary .demo-call[data-demo-event="'+id+'"]')?.getBoundingClientRect().right,
      participant:g?.querySelector('.demo-lane:not(.demo-workflow-row) .demo-call[data-demo-event="'+id+'"]')?.getBoundingClientRect().right};}
  return {width:innerWidth,overflow:document.documentElement.scrollWidth-innerWidth,
    at:demoUi.time,end:demoUi.data.end,total:demoSnapshot().total.known_subtotals.USD||'0.00',
    axis:rect(axis),svg:rect(svg),summary:track(summary),participant:track(participant),
    summaryMarker:oren?.querySelector('.demo-track-summary .demo-event[data-demo-event="'+event+'"]')?
      center(oren.querySelector('.demo-track-summary .demo-event[data-demo-event="'+event+'"]')):null,
    participantMarker:oren?.querySelector('.demo-lane:not(.demo-workflow-row) .demo-event[data-demo-event="'+event+'"]')?
      center(oren.querySelector('.demo-lane:not(.demo-workflow-row) .demo-event[data-demo-event="'+event+'"]')):null,
    chartCursor:chartCursor?.getBoundingClientRect().left,
    guide:guide?.getBoundingClientRect().left,bars};
})()"""

TOLERANCE_PX = 2.5


def close(actual, expected, label, differences):
    if actual is None or abs(actual - expected) > TOLERANCE_PX:
        raise AssertionError(f"{label}: {actual} versus {expected} (tolerance {TOLERANCE_PX}px)")
    differences.append({"surface": label, "difference_px": round(actual - expected, 3)})


def measure(browser):
    return browser.evaluate(GEOMETRY)


def check_plot(data, seconds, differences, *, participant=False, event=False):
    assert data["overflow"] <= 1, data
    x = data["axis"]["left"] + data["axis"]["width"] * seconds / data["end"]
    close(data["summary"]["left"], data["axis"]["left"], "summary origin", differences)
    close(data["summary"]["right"], data["axis"]["right"], "summary end", differences)
    close(data["svg"]["left"], data["axis"]["left"], "cost origin", differences)
    close(data["svg"]["right"], data["axis"]["right"], "cost end", differences)
    close(data["summary"]["cursor"], x, f"summary cursor at {seconds}", differences)
    close(data["chartCursor"], x, f"cost cursor at {seconds}", differences)
    if event:
        close(data["summaryMarker"], x, f"summary marker at {seconds}", differences)
        close(data["guide"], x, f"selected guide at {seconds}", differences)
    if participant:
        close(data["participant"]["left"], data["axis"]["left"], "participant origin", differences)
        close(data["participant"]["right"], data["axis"]["right"], "participant end", differences)
        close(data["participant"]["cursor"], x, f"participant cursor at {seconds}", differences)
        if event:
            close(data["participantMarker"], x, f"participant marker at {seconds}", differences)
            close(
                data["participantMarker"],
                data["summaryMarker"],
                "expanded versus collapsed event",
                differences,
            )


def main():
    destination = ROOT / ".artifacts/browser/dev-09/TEAM-DEMO-ALIGNMENT-RESULT-02.json"
    if destination.exists():
        raise SystemExit("alignment result exists; preserve one-use evidence")
    fixture_test = ReportingTests("test_fixture_conservation_replacement_and_cohorts")
    fixture_test.setUp()
    server = None
    try:
        store, registry = fixture_test.store, fixture_test.registry

        def counters():
            return {
                name: store.db.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
                for name in ("submissions", "intents", "guard_dispatches")
            }

        before = counters()
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
            build={"commit": "dev09-alignment-disposable", "dirty": True},
            web_root=ROOT / "web",
            worker_probe=lambda: {"state": "not configured"},
            sender_status=lambda: {"state": "not configured"},
            registry=registry,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        observations, differences = [], []
        with tempfile.TemporaryDirectory(prefix="ezllmrouter-dev09-alignment-") as scratch:
            with HeadlessChrome(Path(scratch), f"http://127.0.0.1:{port}/") as browser:
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
                call(browser, "click", "Open demo workspace")
                wait(browser, "demoUi.data?.identity==='dev09-team-scripted-cost-demo-v2'", "demo")
                call(browser, "click", "Team activity")
                wait(browser, "demoUi.story==='team'&&demoUi.data?.end===115", "team")
                for width in (1440, 900, 640):
                    browser.call(
                        "Emulation.setDeviceMetricsOverride",
                        {"width": width, "height": 913, "deviceScaleFactor": 1, "mobile": False},
                    )
                    browser.evaluate("demoSeek(0);true")
                    start = measure(browser)
                    assert start["total"] == "0.00" and start["at"] == 0, start
                    check_plot(start, 0, differences)
                    browser.evaluate("demoSeek(demoUi.data.end);true")
                    end = measure(browser)
                    assert end["total"] == "1.25" and end["at"] == 115, end
                    check_plot(end, 115, differences)
                    browser.evaluate("demoSelect('demo.event.oren.ask');true")
                    collapsed = measure(browser)
                    assert collapsed["at"] == 10 and collapsed["participant"] is None, collapsed
                    check_plot(collapsed, 10, differences, event=True)
                    browser.evaluate(
                        "[...document.querySelectorAll('.demo-workflow-group')]"
                        ".find(g=>g.querySelector('strong')?.textContent.startsWith('Oren'))"
                        ".querySelector('button').click();true"
                    )
                    expanded = measure(browser)
                    check_plot(expanded, 10, differences, participant=True, event=True)
                    close(
                        expanded["summaryMarker"],
                        collapsed["summaryMarker"],
                        "expand preserves summary event",
                        differences,
                    )
                    if width == 1440:
                        browser.call(
                            "Emulation.setDeviceMetricsOverride",
                            {
                                "width": 1440,
                                "height": 1200,
                                "deviceScaleFactor": 1,
                                "mobile": False,
                            },
                        )
                        capture_layout = browser.evaluate(
                            "(()=>{const chart=document.querySelector('.demo-viz svg')"
                            ".getBoundingClientRect();return {chart_bottom:chart.bottom,viewport:innerHeight}})()"
                        )
                        assert capture_layout["chart_bottom"] <= capture_layout["viewport"], (
                            capture_layout
                        )
                        shot = screenshot(browser, Path(scratch), "selected-oren-request-aligned")
                        browser.call(
                            "Emulation.setDeviceMetricsOverride",
                            {
                                "width": width,
                                "height": 913,
                                "deviceScaleFactor": 1,
                                "mobile": False,
                            },
                        )
                    browser.evaluate(
                        "[...document.querySelectorAll('.demo-workflow-group')]"
                        ".find(g=>g.querySelector('strong')?.textContent.startsWith('Oren'))"
                        ".querySelector('button').click();true"
                    )
                    recollapsed = measure(browser)
                    check_plot(recollapsed, 10, differences, event=True)
                    close(
                        recollapsed["summaryMarker"],
                        collapsed["summaryMarker"],
                        "collapse preserves summary event",
                        differences,
                    )
                    browser.evaluate(
                        "demoSelect('demo.attempt.brant.boole.check.done');"
                        "for(const name of ['Brant','Andrew · delivery','Andrew · direct'])"
                        "[...document.querySelectorAll('.demo-workflow-group')]"
                        ".find(g=>g.querySelector('strong')?.textContent.startsWith(name))"
                        ".querySelector('button').click();true"
                    )
                    simultaneous = measure(browser)
                    assert simultaneous["at"] == 65 and simultaneous["total"] == "0.84", (
                        simultaneous
                    )
                    check_plot(simultaneous, 65, differences)
                    x65 = simultaneous["axis"]["left"] + simultaneous["axis"]["width"] * 65 / 115
                    close(simultaneous["guide"], x65, "65-second selected guide", differences)
                    for name, surfaces in simultaneous["bars"].items():
                        close(
                            surfaces["summary"], x65, name + " summary usage endpoint", differences
                        )
                        close(
                            surfaces["participant"],
                            x65,
                            name + " participant usage endpoint",
                            differences,
                        )
                    observations.append(
                        {
                            "width": width,
                            "start": start,
                            "end": end,
                            "collapsed_10": collapsed,
                            "expanded_10": expanded,
                            "recollapsed_10": recollapsed,
                            "simultaneous_65": simultaneous,
                        }
                    )
                    browser.evaluate("demoUi.expanded.clear();demoDraw();true")
                browser.evaluate("demoChange({collection:'expanded',story:'expanded_all'});true")
                wait(
                    browser,
                    "demoUi.data?.collection==='expanded'&&demoUi.data?.end>115",
                    "expanded",
                )
                browser.evaluate("demoSeek(demoUi.data.end);true")
                assert browser.evaluate(
                    "demoSnapshot().total.known_subtotals.USD==='1.39'&&"
                    "demoSnapshot().total.attempts===33"
                ), "expanded total changed"
                legacy = browser.evaluate(
                    "fetch('/operator/v1/demo-workspace?collection=legacy&story=all')"
                    ".then(r=>r.json())"
                )
                assert legacy["all_total"]["known_subtotals"]["USD"] == "0.46", legacy
            assert counters() == before, "disposable operational counters changed"
            target = (
                destination.parent / "screenshots/dev09-team-alignment-02-selected-oren-request.png"
            )
            if target.exists():
                raise RuntimeError("alignment screenshot exists; preserve one-use evidence")
            shutil.copy2(Path(scratch) / shot["file"], target)
            result = {
                "status": "PASS",
                "fixture": "dev09-team-scripted-cost-demo-v2",
                "checkpoint": "6a58030e4c8c1c03dfb08cce73e5365b8edd4dc7",
                "scope": "disposable authenticated Chrome, temporary SQLite, no model worker",
                "tolerance_px": TOLERANCE_PX,
                "max_absolute_difference_px": max(abs(row["difference_px"]) for row in differences),
                "differences": differences,
                "observations": observations,
                "totals_usd": {
                    "legacy": "0.46",
                    "team": "1.25",
                    "expanded": "1.39",
                    "team_at_65": "0.84",
                },
                "traffic_before_after": {"before": before, "after": counters()},
                "source_sha256": {
                    name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                    for name in (
                        "web/app.css",
                        "web/demo_workspace_team_view.js",
                        "web/dev09_demo_fixture.json",
                        "web/dev09_team_demo_fixture.json",
                    )
                },
                "screenshot": {"path": str(target.relative_to(ROOT)), "sha256": shot["sha256"]},
            }
            destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
            print(
                json.dumps(
                    {
                        key: result[key]
                        for key in (
                            "status",
                            "fixture",
                            "tolerance_px",
                            "max_absolute_difference_px",
                            "totals_usd",
                            "traffic_before_after",
                            "screenshot",
                        )
                    },
                    sort_keys=True,
                )
            )
    finally:
        if server:
            server.shutdown()
            server.server_close()
            server.operator_jobs.shutdown(wait=True)
            thread.join(timeout=3)
        fixture_test.doCleanups()


if __name__ == "__main__":
    main()
