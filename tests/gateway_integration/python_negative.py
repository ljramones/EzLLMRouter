"""Installed-client probes of post-binding gateway mutations."""
from copy import deepcopy
from pathlib import Path
import json
import os
import sys

import httpx
from ezllmrouter_client import EzLLMRouterClient, EzLLMRouterError


BASE = json.loads(Path(__file__).with_name("request.json").read_text())
CORPUS = json.loads(Path(__file__).with_name("scenarios.json").read_text())


def count():
    with httpx.Client(trust_env=False) as client:
        return len(client.get(os.environ["EZLLMROUTER_RECEIVER_URL"] + "/observations").json()["arrivals"])


def main():
    mode = sys.argv[1]
    if mode not in ("tool", "destination", "content"):
        raise SystemExit("usage: python_negative.py tool|destination|content")
    request = deepcopy(BASE)
    request["step_id"] = "step.dev04.negative." + mode
    if mode == "tool":
        request.update(requested_features=["text", "tools"],
                       tool_definitions=[CORPUS["tool_definition"]], tool_choice="auto")
        request["messages"][1]["blocks"][0]["text"] = "Use lookup for synthetic."
    before = count()
    with EzLLMRouterClient(os.environ["EZLLMROUTER_SERVICE_URL"], os.environ["EZLLMROUTER_DEV_TOKEN"]) as client:
        try:
            client.submit(request, {"wait_ms": 3000})
        except EzLLMRouterError as exc:
            if exc.code != "FDC_REJECTED" or exc.http_status != 409:
                raise
            if count() != before:
                raise AssertionError("negative reached receiver")
            print(json.dumps({"actor": "installed-python", "negative": mode,
                              "code": exc.code, "receiver_delta": 0}))
        else:
            raise AssertionError("mutated request accepted")


if __name__ == "__main__":
    main()
