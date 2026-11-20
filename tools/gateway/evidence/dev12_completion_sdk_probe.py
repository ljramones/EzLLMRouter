"""No-network paired wire-0.3 status checks against an unpacked exact wheel."""

from __future__ import annotations

if not __package__:
    import sys
    from pathlib import Path

    for _parent in Path(__file__).resolve().parents:
        if (_parent / "tools/gateway/__init__.py").is_file():
            sys.path.insert(0, str(_parent))
            break
        if (_parent / "server/tools/gateway/__init__.py").is_file():
            sys.path.insert(0, str(_parent / "server"))
            break


from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys


def main():
    installed, evidence = map(Path, sys.argv[1:3])
    sys.path.insert(0, str(installed))
    from ezllmrouter_client import EzLLMRouterClient, EzLLMRouterError

    fixture = json.loads(evidence.read_text())["payload"]["live_target"]["python_status"]
    handle = fixture["handle"]
    selectors = (
        {"submission_id": handle["submission_id"]},
        {
            "work_selector": {
                key: handle["work_key"][key]
                for key in ("task_id", "step_id", "step_revision", "execution_generation")
            }
        },
    )
    outcomes = []

    class Response:
        def __init__(self, body, header):
            self.content = body
            self.status_code = 200
            self.headers = {"EzLLMRouter-Contract-Version": header}

    class Transport:
        def __init__(self, response):
            self.response = response
            self.calls = []

        def request(self, method, url, *, headers, **kwargs):
            self.calls.append(
                {
                    "method": method,
                    "url": url,
                    "contract_version": headers["EzLLMRouter-Contract-Version"],
                }
            )
            return self.response

    for selector in selectors:
        for name in ("positive", "unknown_version", "unknown_field"):
            body = deepcopy(fixture)
            header = "0.3"
            if name == "unknown_version":
                body["contract_version"] = "0.4"
                header = "0.4"
            elif name == "unknown_field":
                body["unregistered_field"] = "forbidden"
            raw = json.dumps(
                body, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode()
            transport = Transport(Response(raw, header))
            client = EzLLMRouterClient(
                "http://127.0.0.1:1", "synthetic-local-only", transport=transport
            )
            try:
                observed = client.get_successor_status(selector)
                result = "accepted" if observed == fixture else "wrong_result"
            except EzLLMRouterError as error:
                result = error.code
            expected = {
                "positive": "accepted",
                "unknown_version": "UNSUPPORTED_VERSION",
                "unknown_field": "INTERNAL_UNAVAILABLE",
            }[name]
            outcomes.append(
                {
                    "case": name,
                    "selector": "submission_id" if "submission_id" in selector else "work_selector",
                    "http_status": 200,
                    "response_header": header,
                    "exact_body_utf8": raw.decode(),
                    "body_sha256": sha256(raw).hexdigest(),
                    "observed": result,
                    "expected": expected,
                    "request": transport.calls,
                    "passed": result == expected and len(transport.calls) == 1,
                }
            )
    print(
        json.dumps(
            {
                "kind": "dev12_exact_wheel_sdk_probe_v1",
                "wheel_root": str(installed),
                "fixture_sha256": sha256(evidence.read_bytes()).hexdigest(),
                "outcomes": outcomes,
            },
            sort_keys=True,
        )
    )
    if not all(row["passed"] for row in outcomes):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
