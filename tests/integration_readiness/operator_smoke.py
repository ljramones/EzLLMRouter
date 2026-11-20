"""Read-only operator HTTP smoke for the installed accounting-only release."""

import http.client
import json
from pathlib import Path
import sys

artifacts = Path(sys.argv[1])
password = (artifacts / "secrets/operator.password").read_text().strip()
port = 48761
origin = f"http://127.0.0.1:{port}"


def request(method, path, body=None, cookie=None, csrf=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Host": f"127.0.0.1:{port}"}
    if method == "POST":
        headers["Origin"] = origin
    if cookie:
        headers["Cookie"] = cookie
    if csrf:
        headers["X-EzLLMRouter-CSRF"] = csrf
    if body is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(body)
    try:
        connection.request(method, path, body, headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


status, _, page = request("GET", "/integration")
assert status == 200 and b"External accounting" in page
status, _, script = request("GET", "/integration_view.js")
assert status == 200 and b"Register external provider account" in script
status, headers, raw = request("POST", "/operator/v1/login", {"password": password})
assert status == 200
cookie = headers["Set-Cookie"].split(";", 1)[0]
csrf = json.loads(raw)["csrf"]
status, _, raw = request("GET", "/operator/v1/integration/datasets", cookie=cookie)
datasets = json.loads(raw)
assert status == 200 and len(datasets["items"]) == 1
dataset_id = datasets["items"][0]["dataset_id"]
status, _, raw = request(
    "GET", "/operator/v1/integration/accounts?dataset_id=" + dataset_id, cookie=cookie
)
assert status == 200 and json.loads(raw)["items"][0]["state"] == "disabled"
account = {
    "account_id": "account.synthetic.operator",
    "dataset_id": dataset_id,
    "provider_id": "provider.synthetic",
    "credential_ref": "vega.manager.operator",
    "allowed_models": ["model.synthetic"],
    "state": "usable",
}
assert request("POST", "/operator/v1/integration/accounts", account, cookie, csrf)[0] == 201
assert (
    request(
        "POST",
        "/operator/v1/integration/accounts/account.synthetic.operator/state",
        {"dataset_id": dataset_id, "expected_revision": 1, "state": "disabled"},
        cookie,
        csrf,
    )[0]
    == 200
)
colon_account = {**account, "account_id": "account:operator:encoded"}
assert request("POST", "/operator/v1/integration/accounts", colon_account, cookie, csrf)[0] == 201
assert (
    request(
        "POST",
        "/operator/v1/integration/accounts/account%3Aoperator%3Aencoded/state",
        {"dataset_id": dataset_id, "expected_revision": 1, "state": "disabled"},
        cookie,
        csrf,
    )[0]
    == 200
)
assert (
    request(
        "POST",
        "/operator/v1/integration/accounts/account%2Fbad/state",
        {"dataset_id": dataset_id, "expected_revision": 1, "state": "disabled"},
        cookie,
        csrf,
    )[0]
    == 400
)
assert (
    request("GET", "/operator/v1/integration/accounts?dataset_id=" + dataset_id, cookie=cookie)[0]
    == 200
)
status, _, raw = request(
    "GET", "/operator/v1/integration/report?dataset_id=" + dataset_id, cookie=cookie
)
report = json.loads(raw)
assert status == 200 and report["known_total_by_currency"] == {"USD": "0.055000000"}
assert request("GET", "/operator/v1/providers", cookie=cookie)[0] == 404
assert request("GET", "/operator/v1/integration/report?dataset_id=" + dataset_id)[0] == 401
print(
    "installed operator HTTP PASS: UI assets, CSRF account registration/disable, report, disabled provider routes"
)
