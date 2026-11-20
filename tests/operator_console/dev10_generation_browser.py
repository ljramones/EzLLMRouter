#!/usr/bin/env python3
"""One controlled normal-console generation click against the disposable Docker service."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "deploy/local"))
from browser_cdp import HeadlessChrome
from crud_browser import HELPERS, call, screenshot, wait, wait_initial_page


def main():
    status_only = len(sys.argv) == 3 and sys.argv[1] == "--status"
    if len(sys.argv) != 2 and not status_only:
        raise SystemExit("usage: dev10_generation_browser.py [--status] ONE_USE_RUN_DIRECTORY")
    run = Path(sys.argv[-1])
    if not run.is_dir() or any(run.iterdir()):
        raise SystemExit("fresh one-use browser directory required")
    with HeadlessChrome(run, "http://127.0.0.1:8790/") as browser:
        wait_initial_page(browser)
        for _ in range(150):
            if browser.evaluate(
                "document.readyState==='complete'&&typeof api==='function'&&typeof state==='object'"
            ):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("normal console scripts did not finish loading")
        browser.evaluate(HELPERS)
        browser.evaluate(
            "window.confirm=()=>true;document.querySelector('#password').value="
            + json.dumps("dev10-synthetic-browser-password-000000000000")
            + ";document.querySelector('#login-form').requestSubmit();true"
        )
        for _ in range(150):
            if browser.evaluate(
                "!!document.querySelector('#workspace')&&!document.querySelector('#workspace').hidden"
            ):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError(
                "authenticated workspace did not open: "
                + str(
                    browser.evaluate(
                        "({url:location.href,error:document.querySelector('#login-error')?.textContent,"
                        "message:document.querySelector('#view-message')?.textContent,"
                        "workspaceHidden:document.querySelector('#workspace')?.hidden,"
                        "loginHidden:document.querySelector('#login-view')?.hidden,"
                        "role:state.role,principal:state.principal})"
                    )
                )
            )
        browser.evaluate(HELPERS)
        browser.evaluate(
            "location.hash='#/providers/openai/connections/conn.dev08-controlled';true"
        )
        wait(
            browser,
            "document.querySelector('#view-content').textContent.includes('Personal testing · finite allowance')",
            "normal provider detail",
        )
        if status_only:
            wait(
                browser,
                "document.querySelector('#view-content').textContent.includes('USD 0.019991000')",
                "settled campaign status",
            )
            browser.evaluate(
                "[...document.querySelectorAll('#view-content h2')].find(x=>x.textContent.includes('Personal testing'))?.scrollIntoView();true"
            )
            shot = screenshot(browser, run, "dev10-controlled-generation-campaign-status")
            print(
                json.dumps(
                    {"status": "PASS", "read_only": True, "screenshot": shot}, sort_keys=True
                )
            )
            return
        call(browser, "click", "Configure allowance")
        expiry = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        call(
            browser,
            "submit",
            {
                "configuration_ref": "cfg.provider.dev08-controlled",
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
            "draft allowance",
        )
        call(browser, "click", "Activate allowance")
        wait(
            browser,
            "document.querySelector('#view-content').textContent.includes('Run one live test')",
            "active allowance",
        )
        call(browser, "click", "Run one live test")
        wait(
            browser,
            "!!document.querySelector('#view-content form [name=acknowledge_external_send]')",
            "normal validation form",
        )
        if browser.evaluate("document.querySelector('[name=acknowledge_external_send]').checked"):
            raise AssertionError("generation acknowledgement preselected")
        browser.evaluate(
            "document.querySelector('[name=max_output_tokens]').value='32';"
            "const agree=document.querySelector('[name=acknowledge_external_send]');"
            "agree.checked=true;agree.dispatchEvent(new Event('change',{bubbles:true}));"
            "const button=[...document.querySelectorAll('#view-content form button')].find(b=>b.textContent.trim()==='Send one request');"
            "button.click();button.click();true"
        )
        wait(
            browser,
            "document.querySelector('#view-content').textContent.includes('Live test result · this page only')",
            "normal live result",
        )
        text = browser.evaluate("document.querySelector('#view-content').textContent")
        expected = (
            "Hello.",
            "USD 0.000009000",
            "USD 0.019991000",
            "1 / 1",
            "test-response-model",
            "Input tokens5",
            "Output text tokens2",
        )
        if any(part not in text for part in expected):
            raise AssertionError(
                "browser output, usage or allowance display mismatch: "
                + repr([part for part in expected if part not in text])
            )
        if browser.evaluate("document.body.scrollWidth>window.innerWidth+1"):
            raise AssertionError("browser result has horizontal overflow")
        shot = screenshot(browser, run, "dev10-controlled-generation-result")
        # Refresh and status reads use existing records; they must not create work.
        browser.evaluate("document.querySelector('#refresh').click();true")
        wait(
            browser,
            "document.querySelector('#view-content').textContent.includes('USD 0.019991000')",
            "read-only allowance refresh",
        )
        campaign = browser.evaluate("api('/operator/v1/personal-campaign')")
        if (
            campaign["request_count"] != 1
            or campaign["incurred_decimal"] != "0.000009000"
            or campaign["available_decimal"] != "0.019991000"
            or campaign["outstanding_decimal"] != "0"
        ):
            raise AssertionError("read-only campaign status mismatch")
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "normal_ui_button": "Run one live test",
                    "double_click_same_form": True,
                    "displayed_output": "Hello.",
                    "displayed_input_tokens": 5,
                    "displayed_output_tokens": 2,
                    "displayed_cost_decimal": campaign["incurred_decimal"],
                    "displayed_request_count": campaign["request_count"],
                    "displayed_available_decimal": campaign["available_decimal"],
                    "displayed_outstanding_decimal": campaign["outstanding_decimal"],
                    "read_only_refresh_and_status": True,
                    "screenshot": shot,
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
