"""Installed local operator route and UI asset check with encoded account IDs."""
import http.client
import json
from pathlib import Path
import sys

instance = Path(sys.argv[1])
password = (instance / "secrets/operator.password").read_text().strip()
origin = "http://127.0.0.1:48761"


def request(method, path, body=None, cookie=None, csrf=None):
    connection = http.client.HTTPConnection("127.0.0.1", 48761, timeout=5)
    headers = {"Host": "127.0.0.1:48761"}
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


assert request("GET", "/integration")[0] == 200
status, _, ui = request("GET", "/integration_view.js")
assert status == 200 and b"encodeURIComponent(item.account_id)" in ui
status, headers, raw = request("POST", "/operator/v1/login", {"password": password})
assert status == 200
cookie = headers["Set-Cookie"].split(";", 1)[0]
csrf = json.loads(raw)["csrf"]
did = "dataset.integration.correction.v2"
status, _, raw = request("GET", "/operator/v1/integration/report?dataset_id=" + did, cookie=cookie)
assert status == 200 and json.loads(raw)["known_total_by_currency"] == {"USD": "0.030000000"}
account = {"account_id": "account:operator:route", "dataset_id": did, "provider_id": "provider.synthetic",
           "credential_ref": "manager.operator.synthetic", "allowed_models": ["model.synthetic"], "state": "usable"}
assert request("POST", "/operator/v1/integration/accounts", account, cookie, csrf)[0] == 201
state = {"dataset_id": did, "expected_revision": 1, "state": "disabled"}
assert request("POST", "/operator/v1/integration/accounts/account%3Aoperator%3Aroute/state",
               state, cookie, csrf)[0] == 200
assert request("POST", "/operator/v1/integration/accounts/account%2Fbad/state",
               state, cookie, csrf)[0] == 400
assert request("POST", "/operator/v1/integration/accounts/account%GG/state",
               state, cookie, csrf)[0] == 400
assert request("GET", "/operator/v1/integration/report?dataset_id=" + did)[0] == 401
print(json.dumps({"result": "PASS", "ui_asset": True, "encoded_account_change": True,
                  "invalid_encodings_denied": 2, "known_usd": "0.030000000"}, sort_keys=True))
