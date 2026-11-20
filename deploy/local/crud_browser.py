"""One-use, actual Chrome DOM workflow for disposable DEV-07 registry records."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

from browser_cdp import HeadlessChrome


HELPERS = r"""
window.__crud = {
  wait: async function(predicate, label) {
    const until=Date.now()+15000;
    while(Date.now()<until){if(predicate())return true;await new Promise(resolve=>setTimeout(resolve,60));}
    throw Error('Timed out waiting for '+label+'; '+document.querySelector('#view-message')?.textContent);
  },
  button: function(label, scope='#view-content') {
    const button=[...document.querySelectorAll(scope+' button')].find(x=>x.textContent.trim()===label);
    if(!button)throw Error('Button missing: '+label);
    return button;
  },
  click: function(label, scope) {this.button(label,scope).click();return true;},
  rowClick: function(identifier,label) {
    const row=[...document.querySelectorAll('#view-content tr')].find(x=>x.textContent.includes(identifier));
    if(!row)throw Error('Row missing: '+identifier);
    const button=[...row.querySelectorAll('button')].find(x=>x.textContent.trim()===label);
    if(!button)throw Error('Row action missing: '+label);
    button.click();return true;
  },
  fill: function(name,value) {
    const control=document.querySelector('#view-content form [name="'+name+'"]');
    if(!control)throw Error('Form field missing: '+name);
    control.value=String(value);
    control.dispatchEvent(new Event('input',{bubbles:true}));
    control.dispatchEvent(new Event('change',{bubbles:true}));
  },
  submit: async function(values) {
    const form=document.querySelector('#view-content form.registry-form');
    if(!form)throw Error('Registry form missing');
    for(const [name,value] of Object.entries(values))this.fill(name,value);
    form.requestSubmit();
    await this.wait(()=>!form.isConnected||!!form.querySelector('.error')?.textContent,'form commit');
    if(form.isConnected)throw Error('Form rejected: '+form.querySelector('.error')?.textContent);
    return true;
  },
  navigate: async function(view) {
    document.querySelector('#navigation button[data-view="'+view+'"]').click();
    await this.wait(()=>document.querySelector('#navigation button[data-view="'+view+'"]').getAttribute('aria-current')==='page'&&
      !document.querySelector('#view-message')?.textContent.startsWith('Loading'),'navigation '+view);
    return true;
  },
  toggle: function(label) {
    const input=[...document.querySelectorAll('#view-content label')].find(x=>x.textContent.includes(label))?.querySelector('input[type=checkbox]');
    if(!input)throw Error('Filter missing: '+label);
    input.checked=true;input.dispatchEvent(new Event('change',{bubbles:true}));return true;
  }
}; true;
"""


def call(browser, method, *args):
    return browser.evaluate(f"__crud.{method}({','.join(json.dumps(arg) for arg in args)})")


def wait(browser, expression, label):
    return browser.evaluate(f"__crud.wait(()=>({expression}),{json.dumps(label)})")


def wait_initial_page(browser):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if browser.evaluate("!!document.querySelector('#login-form')"):
            return
        time.sleep(0.1)
    raise RuntimeError("local operator login page did not load")


def screenshot(browser, run, name):
    path = Path(run) / (name + ".png")
    browser.screenshot(path)
    return {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def run_browser(run, password, model_ref, user_id, synthetic_ref, url="http://127.0.0.1:8780/"):
    """Use the real console forms; never submit a demo or provider request."""
    shots = []
    with HeadlessChrome(run, url) as browser:
        wait_initial_page(browser)
        browser.evaluate(HELPERS)
        browser.evaluate(
            "document.querySelector('#password').value="
            + json.dumps(password)
            + ";document.querySelector('#login-form').requestSubmit();true"
        )
        wait(browser, "!document.querySelector('#workspace').hidden", "authenticated workspace")
        call(browser, "navigate", "models")
        call(browser, "click", "Add model")
        wait(
            browser,
            "!!document.querySelector('#view-content form [name=local_key]')",
            "model creation form",
        )
        if browser.evaluate("document.activeElement.name") != "local_key":
            raise RuntimeError("model form did not focus its first field")
        browser.call(
            "Input.dispatchKeyEvent",
            {"type": "keyDown", "key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9},
        )
        browser.call(
            "Input.dispatchKeyEvent",
            {"type": "keyUp", "key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9},
        )
        if browser.evaluate("document.activeElement.name") != "display_name":
            raise RuntimeError("keyboard Tab did not reach model display name")
        call(
            browser,
            "submit",
            {
                "local_key": model_ref.removeprefix("catalogue.operator."),
                "display_name": "Disposable test catalogue model",
                "vendor": "Test-only vendor",
                "family": "Disposable test",
                "api_model_id": "test-only-api-model",
                "model_version": "test-v1",
                "owner": "owner.local",
                "capabilities": "text",
                "notes": "Disposable operator-entered reference; no publisher claim or provider route",
                "snapshot_id": "test.reference.v1",
                "source_title": "Test-only source placeholder",
                "source_url": "https://example.org/test-reference",
                "band_0_label": "Test-only rate",
                "band_0_input": "1",
                "band_0_output": "2",
                "band_0_cached": "",
            },
        )
        wait(
            browser,
            json.dumps(model_ref)
            + "&&document.querySelector('#view-content')?.textContent.includes("
            + json.dumps(model_ref)
            + ")",
            "created model row",
        )
        shots.append(screenshot(browser, run, "model-created"))
        call(browser, "rowClick", model_ref, "View")
        wait(
            browser,
            "!!document.querySelector('#view-content button')&&document.querySelector('#view-title').textContent.includes('detail')",
            "model detail",
        )
        call(browser, "click", "Update prices")
        call(
            browser,
            "submit",
            {
                "snapshot_id": "test.reference.v2",
                "source_title": "Revised test-only source",
                "source_url": "https://example.org/revised-test-reference",
                "band_0_input": "3",
                "band_0_output": "4",
            },
        )
        wait(
            browser,
            "document.querySelector('#view-content')?.textContent.includes('test.reference.v2')",
            "updated price detail",
        )
        call(browser, "click", "Edit")
        call(browser, "submit", {"display_name": "Edited disposable catalogue model"})
        wait(
            browser,
            "document.querySelector('#view-content')?.textContent.includes('Edited disposable catalogue model')",
            "edited model detail",
        )
        shots.append(screenshot(browser, run, "model-edited-and-repriced"))
        call(browser, "click", "Edit")
        call(browser, "fill", "display_name", "This unsaved text must be discarded")
        call(browser, "click", "Cancel")
        wait(
            browser,
            "!document.querySelector('#view-content form [name=display_name]')",
            "cancelled model edit",
        )
        call(browser, "click", "Delete…")
        wait(
            browser,
            "document.querySelector('#view-content')?.textContent.includes('archived')",
            "archived model detail",
        )
        call(browser, "click", "← Models & Pricing")
        wait(browser, "!!document.querySelector('#view-content input[type=search]')", "model list")
        call(browser, "toggle", "Show archived models")
        wait(
            browser,
            "document.querySelector('#view-content')?.textContent.includes('Edited disposable catalogue model')",
            "archived model row",
        )
        shots.append(screenshot(browser, run, "model-archived"))

        call(browser, "navigate", "users")
        call(browser, "click", "Add user / service")
        call(
            browser,
            "submit",
            {
                "principal_id": user_id,
                "display_name": "Disposable test identity",
                "kind": "human",
                "owner": "owner.local",
                "role": "ordinary",
            },
        )
        wait(
            browser,
            "document.querySelector('#view-content')?.textContent.includes("
            + json.dumps(user_id)
            + ")",
            "created identity row",
        )
        shots.append(screenshot(browser, run, "user-created"))
        call(browser, "rowClick", user_id, "Edit")
        call(browser, "submit", {"display_name": "Edited disposable identity"})
        wait(
            browser,
            "document.querySelector('#view-content')?.textContent.includes('Edited disposable identity')",
            "edited identity detail",
        )
        call(browser, "click", "Manage model access")
        wait(browser, "!!document.querySelector('#view-content form [name=status]')", "grant form")
        call(
            browser,
            "submit",
            {
                "configuration_ref": synthetic_ref,
                "status": "active",
                "purposes": "execution",
                "task_classes": "class.demo",
            },
        )
        wait(
            browser,
            "document.querySelector('#view-content')?.textContent.includes('Explicit model access')",
            "granted identity detail",
        )
        shots.append(screenshot(browser, run, "user-granted"))
        # Explain is a read-only browser request; the identity remains inactive/unbound.
        browser.evaluate(
            "(()=>{const form=[...document.querySelectorAll('#view-content form')].find(x=>x.textContent.includes('Explain'));"
            "if(!form)throw Error('Explain form missing');form.requestSubmit();return true;})()"
        )
        wait(
            browser,
            "document.querySelector('#view-message')?.textContent.includes('Denied')",
            "read-only Explain access",
        )
        call(browser, "click", "Manage model access")
        wait(
            browser,
            "!!document.querySelector('#view-content form [name=status]')",
            "grant removal form",
        )
        call(browser, "submit", {"configuration_ref": synthetic_ref, "status": "removed"})
        call(browser, "click", "Delete…")
        wait(
            browser,
            "document.querySelector('#view-content')?.textContent.includes('revoked')",
            "revoked identity detail",
        )
        call(browser, "click", "← Users & Access")
        wait(browser, "!!document.querySelector('#view-content input[type=search]')", "user list")
        call(browser, "toggle", "Show revoked identities")
        wait(
            browser,
            "document.querySelector('#view-content')?.textContent.includes('Edited disposable identity')",
            "revoked identity row",
        )
        shots.append(screenshot(browser, run, "user-revoked"))
        browser.evaluate("document.querySelector('#logout').click();true")
        wait(browser, "!document.querySelector('#login-view').hidden", "signed-out screen")
        signed_out = browser.evaluate(
            "fetch('/operator/v1/models').then(response=>response.status)"
        )
        if signed_out != 401:
            raise RuntimeError("browser session still authorized after sign-out")
        dialogs = browser.dialogs
        if not any("Discard unsaved changes" in item for item in dialogs):
            raise RuntimeError("unsaved-change browser confirmation missing")
        if not any("Delete Edited disposable catalogue model" in item for item in dialogs):
            raise RuntimeError("model deletion browser confirmation missing")
        if not any("Delete Edited disposable identity" in item for item in dialogs):
            raise RuntimeError("identity deletion browser confirmation missing")
        return {
            "browser": "headless Chrome",
            "screenshots": shots,
            "confirmed_dialogs": ["unsaved cancellation", "model archive", "identity revocation"],
            "keyboard_tab": "passed",
            "sign_out_http": signed_out,
        }
